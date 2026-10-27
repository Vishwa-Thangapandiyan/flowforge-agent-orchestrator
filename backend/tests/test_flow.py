"""Flow order from code (D25), through `flow_of()` only: Python read by `ast`, nothing run, nothing sent."""

import socket
import textwrap
from pathlib import Path

import pytest

from flowforge.flow import flow_of

TRIP_PLANNER = Path(__file__).resolve().parents[2] / "examples" / "trip-planner"


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"flow analysis tried to open a connection: {args!r}")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return root


def edges(flow) -> set[tuple[str, str, str | None]]:
    return {(e.source, e.target, e.when) for e in flow.edges}


def node(flow, node_id):
    found = flow.node(node_id)
    assert found is not None, f"no block {node_id}: {[n.id for n in flow.nodes]}"
    return found


# --- the trip planner: the golden flow -----------------------------------------------------------------------------

def test_the_trip_planner_flow_matches_its_code(no_network):
    result = flow_of(TRIP_PLANNER)
    flow = result.flow
    assert flow.kind == "flow" and flow.source == "code"
    steps = {n.id: n.evidence[0].ref for n in flow.nodes if n.kind in ("llm", "api", "mcp", "local")}
    assert steps == {
        "api-ip-api-com-1": "planner.py:51", "api-nominatim-1": "planner.py:52", "api-nominatim-2": "planner.py:58",
        "api-osrm-1": "planner.py:59", "api-open-meteo-1": "planner.py:60", "mcp-time-1": "planner.py:64",
        "mcp-fetch-1": "planner.py:66", "api-wikipedia-1": "planner.py:67", "mcp-currency-1": "planner.py:68",
        "local-packing-list-1": "planner.py:72", "llm-ollama-1": "planner.py:88", "mcp-files-1": "planner.py:98",
    }
    decisions = {n.id: (n.condition, n.evidence[0].ref) for n in flow.nodes if n.kind == "decision"}
    assert decisions == {"if-1": ("place is None", "planner.py:53"), "if-2": ("sight", "planner.py:57"),
                         "if-3": ("forecast", "planner.py:63"), "if-4": ("forecast", "planner.py:70"),
                         "if-5": ("itinerary", "planner.py:95")}
    assert edges(flow) == {
        ("start-plan", "api-ip-api-com-1", None), ("start-plan", "api-nominatim-1", None),
        ("api-nominatim-1", "if-1", None),
        ("if-1", "stop-1", "yes"),                       # `return` when the city isn't found
        ("if-1", "if-2", "no"), ("if-1", "api-open-meteo-1", "no"),
        ("if-1", "mcp-fetch-1", "no"), ("if-1", "mcp-currency-1", "no"),
        ("if-2", "api-nominatim-2", "yes"), ("api-nominatim-2", "api-osrm-1", None),
        ("api-open-meteo-1", "if-3", None), ("if-3", "mcp-time-1", "yes"),
        ("api-open-meteo-1", "if-4", None), ("if-4", "local-packing-list-1", "yes"),
        ("mcp-fetch-1", "api-wikipedia-1", None),        # Wikipedia is reached through fetch (D21 via)
        # the plan is written from every fact gathered (through `facts`)
        ("api-ip-api-com-1", "llm-ollama-1", None), ("api-osrm-1", "llm-ollama-1", None),
        ("mcp-time-1", "llm-ollama-1", None), ("mcp-fetch-1", "llm-ollama-1", None),
        ("mcp-currency-1", "llm-ollama-1", None),
        ("llm-ollama-1", "if-5", None), ("if-5", "mcp-files-1", "yes"),
    }
    assert node(flow, "api-nominatim-1").what == "find the city"     # the code's own label
    assert node(flow, "local-packing-list-1").what == "packing list"   # no label: the function it calls, as words
    # each decision asks a whole question, from the step that produced what it checks (or the function's input)
    questions = {n.id: n.title for n in flow.nodes if n.kind == "decision"}
    assert questions == {"if-1": 'Did "find the city" fail?', "if-2": "Was a sight given?",
                         "if-3": "Did \"today's weather\" work?", "if-4": "Did \"today's weather\" work?",
                         "if-5": 'Did "write the plan" work?'}
    assert node(flow, "start-plan").evidence[0].ref == "planner.py:48"
    assert node(flow, "mcp-files-1").op.tool == "write_file" and node(flow, "mcp-files-1").op.read_only is False
    assert node(flow, "mcp-time-1").op.read_only is True


def test_weights_are_measured_when_a_check_measured_them_else_estimated():
    flow = flow_of(TRIP_PLANNER, latencies={"api-nominatim": 420.0, "llm-ollama": 300.0}).flow
    nominatim, ollama, osrm = node(flow, "api-nominatim-1"), node(flow, "llm-ollama-1"), node(flow, "api-osrm-1")
    assert (nominatim.estimate_ms, nominatim.estimate_source) == (420.0, "measured")
    assert ollama.estimate_source == "estimate"   # a check sees that it's up, not how long it writes (D25)
    assert osrm.estimate_source == "estimate" and osrm.estimate_ms == 300.0


def test_the_advice_starts_independent_calls_together():
    latencies = {"api-ip-api-com": 210, "api-nominatim": 420, "api-osrm": 640, "api-open-meteo": 180, "mcp-time": 1900,
                 "mcp-fetch": 6800, "mcp-currency": 400, "local-packing-list": 10, "mcp-files": 2400}
    flow = flow_of(TRIP_PLANNER, latencies=latencies).flow
    by_nodes = {tuple(sorted(a.nodes)): a for a in flow.advice}
    first = by_nodes[("api-ip-api-com-1", "api-nominatim-1")]
    assert first.refs == ["planner.py:51", "planner.py:52"] and first.saved_ms == 210
    after = by_nodes[("api-nominatim-2", "api-open-meteo-1", "mcp-currency-1", "mcp-fetch-1")]
    assert after.saved_ms == 420 + 180 + 400   # all four start at once: the time of all but the slowest
    assert "asyncio.gather" in after.text
    # fetch and currency need only values known before the city check: starting them earlier could waste them
    assert "planner.py:53" in after.caveat and "fetch" in after.caveat and "currency" in after.caveat
    assert "Open-Meteo" not in after.caveat   # it needs the city's coordinates: it can't start before the check
    assert all(a.saved_ms > 0 for a in flow.advice)
    # as written: every call one after another. Nominatim is called twice (the city, the sight), Ollama counts its
    # 2.0 s estimate, and Wikipedia is inside fetch's time.
    assert flow.written_ms == sum(latencies.values()) + 420 + 2000


# --- the rules, on small repos -------------------------------------------------------------------------------------

APP = """
    import httpx

    WEATHER = "https://api.weather.test/v1/today"
    NEWS = "https://api.news.test/v2/top"

    async def weather(client):
        return (await client.get(WEATHER)).json()

    async def news(client):
        return (await client.get(NEWS)).json()
"""


def test_data_flows_through_plain_code_and_an_early_return_guards_what_follows(tmp_path):
    write(tmp_path, {"app.py": APP, "main.py": """
        import httpx
        from app import news, weather

        async def run():
            async with httpx.AsyncClient() as client:
                today = await weather(client)
                summary = {"temp": today["t"]}
                if not summary:
                    return
                headlines = await news(client)
                return summary, headlines
    """})
    flow = flow_of(tmp_path).flow
    assert edges(flow) == {("start-run", "api-api-weather-test-1", None), ("api-api-weather-test-1", "if-1", None),
                           ("if-1", "stop-1", "yes"), ("if-1", "api-api-news-test-1", "no")}


def test_calls_the_code_already_gathers_are_drawn_together_and_get_no_advice(tmp_path):
    write(tmp_path, {"app.py": APP, "main.py": """
        import asyncio
        import httpx
        from app import news, weather

        async def run():
            async with httpx.AsyncClient() as client:
                return await asyncio.gather(weather(client), news(client))
    """})
    flow = flow_of(tmp_path).flow
    assert edges(flow) == {("start-run", "api-api-weather-test-1", None), ("start-run", "api-api-news-test-1", None)}
    assert flow.advice == []


def test_two_independent_awaits_one_after_another_get_advice(tmp_path):
    write(tmp_path, {"app.py": APP, "main.py": """
        import httpx
        from app import news, weather

        async def run():
            async with httpx.AsyncClient() as client:
                today = await weather(client)
                headlines = await news(client)
                return today, headlines
    """})
    flow = flow_of(tmp_path).flow
    (advice,) = flow.advice
    assert sorted(advice.nodes) == ["api-api-news-test-1", "api-api-weather-test-1"]
    assert advice.refs == ["main.py:7", "main.py:8"] and advice.caveat is None


def test_a_call_in_a_loop_repeats_and_two_writes_keep_their_order(tmp_path):
    write(tmp_path, {"main.py": """
        import httpx

        ORDERS = "https://api.shop.test/v1/orders"
        MAIL = "https://api.mail.test/v1/send"

        def run(ids):
            for order_id in ids:
                httpx.get(f"{ORDERS}/{order_id}")
            httpx.post(ORDERS, json={"status": "done"})
            httpx.post(MAIL, json={"to": "me"})
    """})
    flow = flow_of(tmp_path).flow
    reads, writes, mail = node(flow, "api-api-shop-test-1"), node(flow, "api-api-shop-test-2"), node(flow, "api-api-mail-test-1")
    assert reads.repeats and not writes.repeats
    assert writes.op.method == "POST" and mail.op.method == "POST"
    assert ("api-api-shop-test-2", "api-api-mail-test-1", None) in edges(flow)   # a write waits for the write before it


def test_entry_points_unwrap_and_each_one_starts_its_own_flow(tmp_path):
    write(tmp_path, {"app.py": APP, "main.py": """
        import asyncio
        import httpx
        from app import news, weather

        async def morning():
            async with httpx.AsyncClient() as client:
                return await weather(client)

        async def evening():
            async with httpx.AsyncClient() as client:
                return await news(client)

        def main():
            asyncio.run(morning())

        if __name__ == "__main__":
            main()
    """})
    flow = flow_of(tmp_path).flow
    starts = {n.id: n.title for n in flow.nodes if n.kind == "start"}
    assert starts == {"start-morning": "morning()", "start-evening": "evening()"}   # main() only wraps morning()


def test_a_module_level_client_makes_its_uses_llm_calls(tmp_path):
    write(tmp_path, {"main.py": """
        from openai import OpenAI

        client = OpenAI(base_url="http://localhost:11434/v1")

        def answer(question):
            return client.chat.completions.create(model="llama3.1:8b", messages=[{"role": "user", "content": question}])
    """})
    flow = flow_of(tmp_path).flow
    assert ("start-answer", "llm-ollama-1", None) in edges(flow)


def test_a_url_written_inside_the_call_is_a_call(tmp_path):
    write(tmp_path, {"main.py": """
        import httpx

        def run():
            return httpx.get("https://api.weather.test/v1/today")
    """})
    flow = flow_of(tmp_path).flow
    assert flow is not None and ("start-run", "api-api-weather-test-1", None) in edges(flow)


def test_a_call_outside_any_function_has_no_flow_to_draw(tmp_path):
    write(tmp_path, {"web/app.js": "fetch('https://api.weather.test/v1/today');\n"})
    result = flow_of(tmp_path)
    assert result.flow is None
    assert result.message == "No function here calls a dependency yet."


def test_nothing_in_the_repo_runs(tmp_path, no_network):
    marker = tmp_path / "ran"
    write(tmp_path, {"main.py": f"""
        import httpx
        open({str(marker)!r}, "w").write("ran")

        def run():
            return httpx.get("https://api.weather.test/v1/today")
    """})
    flow_of(tmp_path)
    assert not marker.exists()


def test_a_key_in_an_if_or_a_label_never_reaches_the_flow(tmp_path):
    key = "sk_test_FAKEFAKE12345678"
    write(tmp_path, {"main.py": f"""
        import httpx

        def note(text):
            return {{"note": text}}

        def run(token):
            if token == "{key}":
                return
            httpx.get("https://api.weather.test/v1/today", params=note("send with {key} attached"))
    """})
    flow = flow_of(tmp_path).flow
    assert any(n.kind == "decision" for n in flow.nodes)
    assert key not in flow.model_dump_json()   # conditions, questions and labels are masked like evidence (D20)


# --- advice you can act on (D27) ------------------------------------------------------------------------------------

LATENCIES = {"api-ip-api-com": 210, "api-nominatim": 420, "api-osrm": 640, "api-open-meteo": 180, "mcp-time": 1900,
             "mcp-fetch": 6800, "mcp-currency": 400, "local-packing-list": 10, "mcp-files": 2400}


def advice_for(flow, *ids):
    return next(a for a in flow.advice if set(a.nodes) == set(ids))


def test_two_awaits_in_a_row_get_the_gather_written_out():
    flow = flow_of(TRIP_PLANNER, latencies=LATENCIES).flow
    first = advice_for(flow, "api-ip-api-com-1", "api-nominatim-1")
    change = first.change
    assert change.path == "planner.py" and change.first_line == 51
    assert change.before == [
        '        home = await attempt("where you are (ip-api)", geo.where_am_i(client))',
        '        place = await attempt("find the city (Nominatim)", geo.find_place(client, city))',
    ]
    assert change.after == [
        "        home, place = await asyncio.gather(",
        "            attempt('where you are (ip-api)', geo.where_am_i(client)),",
        "            attempt('find the city (Nominatim)', geo.find_place(client, city)),",
        "        )",
    ]
    assert change.saved_ms == 210 and change.by_hand == [] and change.needs_import is False
    # the prompt names the file, the function and every line, and asks for nothing else to change
    assert "planner.py" in first.prompt and "plan()" in first.prompt
    assert "line 51" in first.prompt and "line 52" in first.prompt and "Change nothing else" in first.prompt


def test_calls_in_other_blocks_are_left_to_move_by_hand():
    flow = flow_of(TRIP_PLANNER, latencies=LATENCIES).flow
    after = advice_for(flow, "api-nominatim-2", "api-open-meteo-1", "mcp-fetch-1", "mcp-currency-1")
    change = after.change
    assert change.first_line == 66 and change.after[0] == "    background, rate = await asyncio.gather("
    assert change.saved_ms == 400   # fetch and currency together: the time of the faster one
    assert change.by_hand == ['"find the sight" (planner.py:58): inside `if sight:`',
                              '"today\'s weather" (planner.py:60): inside the `async with` block']
    assert "line 58" in after.prompt and after.caveat in after.prompt


def test_no_change_is_written_when_code_between_uses_a_result(tmp_path):
    write(tmp_path, {"app.py": APP, "main.py": """
        import asyncio
        import httpx
        from app import news, weather

        async def run():
            async with httpx.AsyncClient() as client:
                today = await weather(client)
                print(today)
                headlines = await news(client)
                return today, headlines
    """})
    (advice,) = flow_of(tmp_path).flow.advice
    assert advice.change is None
    assert "main.py" in advice.prompt and "asyncio.gather" in advice.prompt


def test_plain_calls_get_a_prompt_but_no_written_change(tmp_path):
    write(tmp_path, {"main.py": """
        import httpx

        def run():
            today = httpx.get("https://api.weather.test/v1/today")
            headlines = httpx.get("https://api.news.test/v2/top")
            return today, headlines
    """})
    (advice,) = flow_of(tmp_path).flow.advice
    assert advice.change is None and "thread pool" in advice.prompt


def test_the_written_change_says_when_asyncio_needs_importing_and_masks_keys(tmp_path):
    key = "sk_test_FAKEFAKE12345678"
    write(tmp_path, {"app.py": APP, "main.py": f"""
        import httpx
        from app import news, weather

        async def run():
            async with httpx.AsyncClient(headers={{"Authorization": "Bearer {key}"}}) as client:
                today = await weather(client, "{key}")
                headlines = await news(client)
                return today, headlines
    """})
    (advice,) = flow_of(tmp_path).flow.advice
    assert advice.change.needs_import is True
    assert key not in advice.model_dump_json()


def test_no_change_is_written_when_a_key_split_over_lines_sits_in_the_block(tmp_path):
    part = "SPLITPARTONE1234"
    write(tmp_path, {"app.py": APP, "main.py": f"""
        import httpx
        from app import news, weather

        async def run():
            async with httpx.AsyncClient() as client:
                today = await weather(client, ("sk_test_FAKEFAKE"
                                               "{part}"))
                headlines = await news(client)
                return today, headlines
    """})
    (advice,) = flow_of(tmp_path).flow.advice
    assert advice.change is None and "asyncio.gather" in advice.prompt
    assert part not in flow_of(tmp_path).flow.model_dump_json()


def test_a_plain_call_beside_an_await_runs_in_a_thread():
    measured = {k: v for k, v in LATENCIES.items() if k != "local-packing-list"}   # its 1 s estimate, then
    flow = flow_of(TRIP_PLANNER, latencies=measured).flow
    mixed = advice_for(flow, "mcp-time-1", "local-packing-list-1")   # packing_list() isn't awaited
    assert "asyncio.to_thread" in mixed.text and "asyncio.to_thread" in mixed.prompt
