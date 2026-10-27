"""Security findings from the scan (D31): what is found, what it belongs to, and that no value ever leaves."""

import json
import logging
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from flowforge import main
from flowforge.agent import build_server
from flowforge.scan import scan
from flowforge.storage import Storage

ROOT = Path(__file__).resolve().parents[2]
TRIP_PLANNER = ROOT / "examples" / "trip-planner"
FAKE = "sk_test_FAKEFAKE12345678"
GOOGLE = "AIzaFAKEFAKEFAKEFAKEFAKE1234"


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return root


def by_kind(root: Path) -> dict[str, list]:
    out: dict[str, list] = {}
    for f in scan(root).findings:
        out.setdefault(f.kind, []).append(f)
    return out


def test_the_trip_planner_shows_exactly_what_it_plants():
    found = scan(TRIP_PLANNER).findings
    assert {(f.kind, f.level, f.ref, f.dep_id) for f in found} == {
        ("key_in_code", "high", "config.py:23", "api-google-maps"),
        ("plain_http", "medium", "config.py:18", "api-ip-api-com"),
        ("unpinned_server", "medium", ".mcp.json:7", "mcp-fetch"),
    }
    key = next(f for f in found if f.kind == "key_in_code")
    assert key.title == "A Google API key is written in the code"
    assert key.excerpt[key.line - key.first_line] == 'GOOGLE_STATIC_MAPS_KEY = "[REDACTED]"'
    assert "replace" in key.fix and "GOOGLE_STATIC_MAPS_KEY" in key.prompt
    assert GOOGLE not in json.dumps([f.model_dump() for f in found])


def test_ids_are_stable_across_scans():
    assert [f.id for f in scan(TRIP_PLANNER).findings] == [f.id for f in scan(TRIP_PLANNER).findings]


def test_mcp_configs_keys_unpinned_servers_and_whole_disk_access(tmp_path):
    repo = write(tmp_path / "app", {
        ".mcp.json": json.dumps({"mcpServers": {
            "search": {"command": "npx", "args": ["-y", "brave-search-mcp"], "env": {"BRAVE_API_KEY": "plainvalue123456"}},
            "pinned": {"command": "npx", "args": ["-y", "@scope/server@1.2.3"], "env": {"TOKEN": "${TOKEN}"}},
            "py": {"command": "uvx", "args": ["mcp-server-git==2025.1.1"]},
            "frompkg": {"command": "uvx", "args": ["--from", "some-tool", "serve"]},
            "disk": {"command": "npx", "args": ["@modelcontextprotocol/server-filesystem@2.0.0", "/"]},
            "home": {"command": "npx", "args": ["@modelcontextprotocol/server-filesystem@2.0.0", "~"]},
            "local": {"command": "python", "args": ["server.py"]},
        }}, indent=2),
    })
    found = by_kind(repo)
    assert [(f.dep_id, f.ref) for f in found["key_in_config"]] == [("mcp-search", ".mcp.json:10")]
    assert sorted(f.dep_id for f in found["unpinned_server"]) == ["mcp-frompkg", "mcp-search"]
    assert sorted(f.dep_id for f in found["broad_files"]) == ["mcp-disk", "mcp-home"]
    everything = json.dumps([f.model_dump() for fs in found.values() for f in fs])
    assert "plainvalue123456" not in everything


def test_plain_http_counts_only_for_hosts_that_arent_local(tmp_path):
    repo = write(tmp_path / "app", {"main.py": """
        import httpx

        def run():
            httpx.get("http://localhost:8080/health")
            httpx.get("http://127.0.0.1:9000/x")
            return httpx.get("http://api.weather.test/v1/today")
    """})
    found = by_kind(repo)
    assert [(f.ref, f.dep_id) for f in found["plain_http"]] == [("main.py:6", "api-api-weather-test")]


def test_test_and_fake_files_are_not_searched(tmp_path):
    repo = write(tmp_path / "app", {
        "tests/test_pay.py": f'KEY = "{FAKE}"\n',
        "fake_data.py": f'KEY = "{FAKE}"\n',
        "main.py": "print('hi')\n",
    })
    assert scan(repo).findings == []


@pytest.fixture
def leaky(tmp_path):
    return write(tmp_path / "leaky", {
        "main.py": f"""
            import httpx

            STRIPE_KEY = "{FAKE}"

            def pay():
                return httpx.post("https://api.stripe.com/v1/charges", headers={{"Authorization": STRIPE_KEY}})
        """,
    })


def test_a_key_appears_in_no_stored_row_api_answer_log_or_agent_answer(leaky, tmp_path, monkeypatch, caplog):
    db = tmp_path / "flowforge.db"
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(db))
    monkeypatch.setenv("FLOWFORGE_REPO", str(leaky))
    caplog.set_level(logging.DEBUG)
    with TestClient(main.app) as client:
        security = client.get("/security").json()
        assert [f["kind"] for f in security["findings"]] == ["key_in_code"]
        assert security["findings"][0]["dep_id"] == "api-stripe"
        answers = [client.get(r.path).text for r in main.app.routes
                   if "GET" in getattr(r, "methods", ()) and "{" not in r.path]
    assert all(FAKE not in text for text in answers)
    assert FAKE.encode() not in db.read_bytes()
    assert FAKE not in caplog.text


async def test_agents_get_the_findings_masked(leaky, tmp_path):
    storage = Storage(tmp_path / "agent.db")
    async with Client(build_server(leaky, storage)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools["get_security_findings"].annotations.read_only_hint is True
        result = await client.call_tool("get_security_findings", {})
    got = json.loads(result.content[0].text)
    assert [f["kind"] for f in got["findings"]] == ["key_in_code"] and got["summary"] == {"high": 1}
    assert FAKE not in result.content[0].text


SPLIT = "SPLITPARTONE1234"
PEM_BODY = "MIIEFAKEPEMBODYFAKEPEMBODYFAKEPEMBODYFAKEPEMBODYFAKEPEMBODY0000"


@pytest.fixture
def split_keys(tmp_path: Path) -> Path:
    """Keys the finders catch but a line-by-line mask can't: split over lines, and a private-key block."""
    return write(tmp_path / "split", {
        "main.py": f'''
            import httpx

            STRIPE_KEY = (
                "sk_test_FAKEFAKE"
                "{SPLIT}"
            )
            PEM = """-----BEGIN RSA PRIVATE KEY-----
            {PEM_BODY}
            -----END RSA PRIVATE KEY-----"""

            def pay():
                return httpx.post("https://api.stripe.com/v1/charges", headers={{"Authorization": STRIPE_KEY}})
        ''',
        "web.js": f'''
            const KEY = "sk_test_FAKEFAKE" +
              "{SPLIT}";
            fetch("https://api.stripe.com/v1/charges", {{ headers: {{ Authorization: KEY }} }});
        ''',
    })


def _no_part(text: str) -> bool:
    return SPLIT not in text and PEM_BODY not in text


async def test_a_key_split_over_lines_appears_nowhere(split_keys, tmp_path, monkeypatch, caplog):
    result = scan(split_keys)
    assert {f.kind for f in result.findings} == {"key_in_code"}
    assert _no_part(result.model_dump_json())
    db = tmp_path / "flowforge.db"
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(db))
    monkeypatch.setenv("FLOWFORGE_REPO", str(split_keys))
    caplog.set_level(logging.DEBUG)
    with TestClient(main.app) as client:
        answers = [client.get(r.path).text for r in main.app.routes
                   if "GET" in getattr(r, "methods", ()) and "{" not in r.path]
        answers += [client.get("/flow", params={"map": m}).text for m in ("deps", "flow")]
    assert all(_no_part(text) for text in answers)
    assert SPLIT.encode() not in db.read_bytes() and PEM_BODY.encode() not in db.read_bytes()
    assert _no_part(caplog.text)
    storage = Storage(tmp_path / "agent.db")
    async with Client(build_server(split_keys, storage)) as agent:
        for tool in ("get_map", "get_flow", "get_security_findings"):
            got = await agent.call_tool(tool, {})
            assert _no_part(got.content[0].text), tool


def test_a_scan_stored_before_findings_existed_is_read_again(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    with TestClient(main.app) as client:
        from flowforge.state import app_state
        flows = app_state().flows["deps"]
        latest = app_state().storage.latest_flow_version("deps")
        analysis = json.loads(latest["analysis"]) if isinstance(latest.get("analysis"), str) else latest["analysis"]
        analysis["scan"].pop("findings_checked")
        analysis["scan"]["findings"] = []
        monkeypatch.setattr(flows, "analysis", lambda: analysis)
        got = client.get("/security").json()
    assert {f["ref"] for f in got["findings"]} == {"config.py:23", "config.py:18", ".mcp.json:7"}
