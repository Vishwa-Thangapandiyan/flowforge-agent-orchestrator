"""Health checks (D24), through `check()` only: APIs and LLMs against httpx's MockTransport, MCP servers as real
stdio processes from tmp folders, local programs on disk. Nothing leaves this machine."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from flowforge import checks
from flowforge.checks import CheckTarget, check
from flowforge.scan.models import EnvName


def client(handler):
    """An HTTP client whose every request goes to `handler`, a function of the request."""
    async def respond(request: httpx.Request) -> httpx.Response:
        out = handler(request)
        return await out if asyncio.iscoroutine(out) else out
    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


def api(target, **fields):
    return CheckTarget(id="api-x", kind="api", name="X", target=target, **fields)


# --- APIs ------------------------------------------------------------------------------------------------------

async def test_an_api_that_answers_is_up_with_its_latency(tmp_path):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200)
    async with client(handler) as http:
        result = await check(api("https://api.weather.test/v1/forecast"), tmp_path, http=http)
    assert result.status == "up" and result.summary == "Up" and result.latency_ms is not None
    # one GET, with no key, cookie or query, saying who it is (D24)
    (request,) = seen
    assert request.method == "GET" and request.url == "https://api.weather.test/v1/forecast"
    assert "authorization" not in request.headers and "cookie" not in request.headers
    assert request.headers["user-agent"].startswith("FlowForge health check")


async def test_an_api_asking_for_a_key_is_up(tmp_path):
    async with client(lambda r: httpx.Response(403)) as http:
        result = await check(api("https://maps.test/staticmap"), tmp_path, http=http)
    assert result.status == "up" and result.summary == "Up, needs a key (403)"


async def test_a_server_error_or_no_answer_is_down(tmp_path):
    async with client(lambda r: httpx.Response(503)) as http:
        assert (await check(api("https://api.flaky.test/"), tmp_path, http=http)).status == "down"

    def refuse(request):
        raise httpx.ConnectError("connection refused")
    async with client(refuse) as http:
        result = await check(api("https://api.gone.test/v1"), tmp_path, http=http)
    assert result.status == "down" and result.summary == "Can't connect" and "refused" in result.reason

    def hang(request):
        raise httpx.ReadTimeout("timed out")
    async with client(hang) as http:
        result = await check(api("https://api.slowpoke.test/v1"), tmp_path, http=http)
    assert result.status == "down" and result.summary == "No answer within 10 s"


async def test_slow_or_unencrypted_needs_a_look(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.probes, "SLOW_MS", 50)
    async def slow(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200)
    async with client(slow) as http:
        result = await check(api("https://api.slow.test/v1"), tmp_path, http=http)
    assert result.status == "warn" and result.summary.startswith("Up, but slow")

    async with client(lambda r: httpx.Response(200)) as http:
        result = await check(api("http://ip-api.test/json/"), tmp_path, http=http)
    assert result.status == "warn" and result.summary == "Up, but plain http://: not encrypted"
    async with client(lambda r: httpx.Response(200)) as http:   # on this machine, http is fine
        assert (await check(api("http://localhost:8080/api"), tmp_path, http=http)).status == "up"


def test_a_certificate_close_to_expiry_needs_a_look():
    now = datetime(2026, 10, 21, tzinfo=UTC)
    soon = (now + timedelta(days=5)).strftime("%b %d %H:%M:%S %Y GMT")
    later = (now + timedelta(days=90)).strftime("%b %d %H:%M:%S %Y GMT")
    assert checks.probes.cert_warning(soon, now) == "its certificate expires in 5 days"
    assert checks.probes.cert_warning(later, now) is None


async def test_an_api_with_no_address_in_the_code_is_skipped(tmp_path):
    result = await check(CheckTarget(id="api-supabase", kind="api", name="Supabase"), tmp_path)
    assert result.status == "skipped" and result.summary == "Not checked: no address in the code"


# --- LLMs ------------------------------------------------------------------------------------------------------

def ollama(model="llama3.1:8b"):
    return CheckTarget(id="llm-ollama", kind="llm", name="Ollama", catalog="ollama", target="localhost:11434",
                       model=model)


async def test_ollama_is_up_when_it_has_the_model(tmp_path):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:latest"}]})
    async with client(handler) as http:
        result = await check(ollama(), tmp_path, http=http)
        assert result.status == "up" and result.summary == "Up, llama3.1:8b is ready"
        assert (await check(ollama("qwen2.5"), tmp_path, http=http)).status == "up"   # ":latest" is implied
        missing = await check(ollama("mistral:7b"), tmp_path, http=http)
    assert seen[0] == "http://localhost:11434/api/tags"
    assert missing.status == "warn" and missing.summary == "Up, but mistral:7b isn't pulled"
    assert missing.fix == "Run `ollama pull mistral:7b`."


async def test_ollama_not_running_is_down_with_a_hint(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("connection refused")
    async with client(refuse) as http:
        result = await check(ollama(), tmp_path, http=http)
    assert result.status == "down" and result.summary == "Nothing answers at localhost:11434"
    assert result.fix == "Start Ollama (`ollama serve`)."


async def test_a_hosted_llm_is_checked_at_its_model_list_without_a_key(tmp_path):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(401)
    target = CheckTarget(id="llm-openai", kind="llm", name="OpenAI", catalog="openai", model="gpt-4o-mini")
    async with client(handler) as http:
        result = await check(target, tmp_path, http=http)
    assert str(seen[0].url) == "https://api.openai.com/v1/models" and "authorization" not in seen[0].headers
    assert result.status == "up" and result.summary == "Up, needs a key (401) to list its models"


# --- MCP servers: real stdio processes ---------------------------------------------------------------------------

SERVER = '''
import os, sys, time
time.sleep(float(os.getenv("SLEEP_S", "0")))
from mcp.server.mcpserver import MCPServer
server = MCPServer("tools")

@server.tool()
def ping() -> str:
    """Answer pong."""
    return "pong"

@server.tool()
def echo(text: str) -> str:
    """Echo text."""
    return text

server.run()
'''


def mcp(command, **fields):
    return CheckTarget(id="mcp-x", kind="mcp", name="x", command=command, **fields)


def script(tmp_path, name, text):
    (tmp_path / "servers").mkdir(exist_ok=True)
    (tmp_path / "servers" / name).write_text(text, encoding="utf-8")
    return ["python", f"servers/{name}"]


async def test_an_mcp_server_that_lists_its_tools_is_up(tmp_path):
    result = await check(mcp(script(tmp_path, "tools.py", SERVER)), tmp_path)
    assert result.status == "up" and result.summary == "Up: 2 tools" and result.detail["tools"] == ["echo", "ping"]
    assert result.latency_ms > 0


async def test_an_mcp_server_that_stops_at_start_up_is_down_with_its_own_words_and_a_likely_fix(tmp_path):
    """The trip planner's currency server, as shipped: it exits because its env var is unset (D24)."""
    command = script(tmp_path, "currency.py", (
        "import os, sys\nif not os.getenv('CURRENCY_API_URL'):\n"
        "    sys.exit('currency server: CURRENCY_API_URL is not set')\n"))
    reads = [EnvName(name="CURRENCY_API_URL", ref="servers/currency.py:2")]
    result = await check(mcp(command, reads_env=reads), tmp_path)
    assert result.status == "down" and result.summary == "Stopped while starting"
    assert "currency server: CURRENCY_API_URL is not set" in result.reason
    assert result.fix == ("Its code reads CURRENCY_API_URL (servers/currency.py:2), "
                          "but its MCP config gives it no env.")


async def test_a_down_mcp_server_names_the_env_its_config_sets_never_the_values(tmp_path):
    command = script(tmp_path, "needy.py", "import sys\nsys.exit('needy: bad token')\n")
    result = await check(mcp(command, env_names=["SHOP_API_TOKEN", "SHOP_URL"]), tmp_path)
    assert result.reason.endswith("Its config sets SHOP_API_TOKEN, SHOP_URL.")


async def test_an_mcp_server_gets_none_of_your_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_API_TOKEN", "sk_test_FAKEFAKE12345678")
    command = script(tmp_path, "nosy.py", "import os, sys\nsys.exit('saw ' + os.getenv('SHOP_API_TOKEN', 'nothing'))\n")
    result = await check(mcp(command), tmp_path)
    assert "saw nothing" in result.reason and "FAKEFAKE" not in result.model_dump_json()


async def test_a_slow_or_silent_mcp_server(tmp_path, monkeypatch):
    monkeypatch.setattr(checks.probes, "MCP_SLOW_MS", 300)
    slow = SERVER.replace('float(os.getenv("SLEEP_S", "0"))', "0.5")
    result = await check(mcp(script(tmp_path, "slow.py", slow)), tmp_path)
    assert result.status == "warn" and result.summary.startswith("Up: 2 tools, but slow to start")

    monkeypatch.setattr(checks.probes, "MCP_TIMEOUT_S", 0.5)
    silent = SERVER.replace('float(os.getenv("SLEEP_S", "0"))', "5")
    result = await check(mcp(script(tmp_path, "silent.py", silent)), tmp_path)
    assert result.status == "down" and result.summary == "No answer within 0.5 s"


async def test_an_mcp_server_with_a_masked_argument_is_not_started(tmp_path):
    result = await check(mcp(["npx", "-y", "some-mcp", "--api-key", "[REDACTED]"]), tmp_path)
    assert result.status == "skipped" and result.summary == "Not checked: its arguments hold a masked secret"


async def test_a_remote_mcp_server_is_checked_like_an_api(tmp_path):
    async with client(lambda r: httpx.Response(405)) as http:
        result = await check(mcp(["https://mcp.example-tools.test/mcp"]), tmp_path, http=http)
    assert result.status == "up"


async def test_a_missing_program_is_down(tmp_path):
    result = await check(mcp(["no-such-program-ff", "serve"]), tmp_path)
    assert result.status == "down" and result.summary == "Can't start: no-such-program-ff isn't installed"


# --- local programs: looked for, never run -----------------------------------------------------------------------

def local(command):
    return CheckTarget(id="local-x", kind="local", name="x", command=command)


async def test_a_local_script_or_program_is_found_and_never_run(tmp_path):
    (tmp_path / "tools").mkdir()
    marker = tmp_path / "ran"
    (tmp_path / "tools" / "packing_list.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    result = await check(local(["python", "tools/packing_list.py"]), tmp_path)
    assert result.status == "up" and result.summary == "Found, not run" and not marker.exists()
    assert (await check(local(["python"]), tmp_path)).status == "up"


async def test_a_missing_script_or_program_is_down(tmp_path):
    result = await check(local(["python", "tools/gone.py"]), tmp_path)
    assert result.status == "down" and result.summary == "Missing: tools/gone.py isn't in the repo"
    result = await check(local(["no-such-program-ff", "--fast"]), tmp_path)
    assert result.status == "down" and result.summary == "Missing: no-such-program-ff isn't installed"


# --- the HTTP client keeps nothing between checks ------------------------------------------------------------

async def test_no_cookie_is_kept_or_sent(tmp_path):
    """D24: no key, cookie or query. A cookie a service sets is never sent back on a later check."""
    seen = []
    def handler(request):
        seen.append(request.headers.get("cookie"))
        return httpx.Response(200, headers={"set-cookie": "session=abc123; Path=/"})
    async with checks.probes.new_client(httpx.MockTransport(handler)) as http:
        await check(api("https://api.cookies.test/v1"), tmp_path, http=http)
        await check(api("https://api.cookies.test/v1"), tmp_path, http=http)
    assert seen == [None, None]
