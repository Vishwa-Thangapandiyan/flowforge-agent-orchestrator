"""The repo scanner (D21): plain code, read-only, no network and no LLM (D20). Tested through `scan()` only."""

import socket
import subprocess
from pathlib import Path

import pytest

from flowforge.scan import scan

TRIP_PLANNER = Path(__file__).resolve().parents[2] / "examples" / "trip-planner"

# The ground truth from examples/trip-planner/README.md: dependency id -> refs that must be among its evidence.
TRIP_PLANNER_DEPENDENCIES = {
    "llm-ollama": {"services/llm.py:5", "services/llm.py:14", "config.py:11"},
    "api-nominatim": {"config.py:15"},
    "api-open-meteo": {"config.py:16"},
    "api-osrm": {"config.py:17"},
    "api-ip-api-com": {"config.py:18"},
    "api-google-maps": {"config.py:24"},
    "api-wikipedia": {"planner.py:67"},
    "mcp-time": {".mcp.json:3"},
    "mcp-fetch": {".mcp.json:7"},
    "mcp-files": {".mcp.json:11"},
    "mcp-currency": {".mcp.json:15"},
    "local-packing-list": {"planner.py:37"},
}


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to open a connection fails the test (D20: the scan sends nothing anywhere)."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"the scan tried to open a connection: {args!r}")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def by_id(result):
    return {d.id: d for d in result.dependencies}


def refs(dep):
    return {e.ref for e in dep.evidence}


def test_a_url_used_in_an_http_call_is_a_confirmed_api_without_its_query(tmp_path):
    write(tmp_path, {"app.py": (
        "import httpx\n"
        "\n"
        'WEATHER = "https://weather.test/today?key=abc123"\n'
        "\n"
        "def today():\n"
        "    return httpx.get(WEATHER)\n"
    )})
    dep = by_id(scan(tmp_path))["api-weather-test"]
    assert dep.kind == "api" and dep.status == "confirmed"
    assert dep.target == "https://weather.test/today"
    assert {"app.py:3", "app.py:6"} <= refs(dep)


def test_links_local_addresses_and_urls_inside_longer_strings_are_not_apis(tmp_path):
    write(tmp_path, {"app.py": (
        'AGENT = "my-app/1.0 (+https://github.com/me/my-app)"\n'
        'LOCAL = "http://localhost:8080/health"\n'
        'PRIVATE = "http://192.168.1.20/status"\n'
        'DOCS = "https://example.com/docs"\n'
        'HOME = "https://www.mysite.test/about"\n'
    )})
    deps = by_id(scan(tmp_path))
    assert set(deps) == {"api-www-mysite-test"}
    assert deps["api-www-mysite-test"].status == "unconfirmed"   # a page link, not a call


def test_an_llm_sdk_is_resolved_to_its_provider_through_constants_in_other_files(tmp_path):
    write(tmp_path, {
        "config.py": (
            "import os\n"
            'BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")\n'
            'MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")\n'
        ),
        "llm.py": (
            "from openai import OpenAI\n"
            "from config import BASE, MODEL\n"
            "\n"
            "def ask(q):\n"
            '    client = OpenAI(base_url=BASE, api_key="unused")\n'
            '    return client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": q}])\n'
        ),
    })
    deps = by_id(scan(tmp_path))
    assert set(deps) == {"llm-ollama"}   # the localhost URL is the LLM, not an API
    dep = deps["llm-ollama"]
    assert dep.kind == "llm" and dep.name == "Ollama" and dep.catalog == "ollama"
    assert dep.target == "localhost:11434" and dep.model == "llama3.1:8b"
    assert {"llm.py:1", "llm.py:5", "config.py:2", "config.py:3"} <= refs(dep)
    assert dep.env_names == ["LLM_BASE_URL", "LLM_MODEL"]


def test_an_llm_sdk_without_a_base_url_is_its_own_provider(tmp_path):
    write(tmp_path, {"bot.py": "import anthropic\n\nclient = anthropic.Anthropic()\n"})
    dep = by_id(scan(tmp_path))["llm-claude"]
    assert dep.name == "Claude" and dep.status == "confirmed" and {"bot.py:1", "bot.py:3"} <= refs(dep)


MCP_CONFIG = """{
  "mcpServers": {
    "time": {"command": "uvx", "args": ["mcp-server-time"]},
    "fetch": {"command": "uvx", "args": ["mcp-server-fetch"], "env": {"FETCH_TOKEN": "sk_test_FAKEFAKE12345678"}}
  }
}
"""


def test_mcp_servers_the_app_reads_are_its_dependencies_and_urls_through_them_record_via(tmp_path):
    write(tmp_path, {
        ".mcp.json": MCP_CONFIG,
        "tools.py": (
            "import json\n"
            "from mcp import ClientSession\n"
            'SERVERS = json.load(open(".mcp.json"))["mcpServers"]\n'
            "\n"
            "async def about(city):\n"
            '    return await call("fetch", "fetch", {"url": f"https://en.wikipedia.org/wiki/{city}"})\n'
        ),
    })
    result = scan(tmp_path)
    deps = by_id(result)
    assert {"mcp-time", "mcp-fetch", "api-wikipedia"} == set(deps)
    assert deps["mcp-time"].scope == deps["mcp-fetch"].scope == "app"
    assert refs(deps["mcp-time"]) == {".mcp.json:3"} and deps["mcp-time"].command == ["uvx", "mcp-server-time"]
    assert deps["mcp-fetch"].env_names == ["FETCH_TOKEN"]
    wiki = deps["api-wikipedia"]
    assert wiki.via == "mcp-fetch" and wiki.status == "confirmed" and refs(wiki) == {"tools.py:6"}
    assert "FAKEFAKE" not in result.model_dump_json()


def test_mcp_servers_only_a_coding_tool_uses_are_their_own_group(tmp_path):
    write(tmp_path, {".mcp.json": MCP_CONFIG, "app.py": "print('hello')\n"})
    deps = by_id(scan(tmp_path))
    assert deps["mcp-time"].scope == deps["mcp-fetch"].scope == "dev_tool"


def test_programs_the_code_runs_are_local_dependencies(tmp_path):
    write(tmp_path, {"jobs.py": (
        "import os, subprocess, sys\n"
        "from pathlib import Path\n"
        "HERE = Path(__file__).parent\n"
        "\n"
        "def pack(t):\n"
        '    subprocess.run([sys.executable, str(HERE / "tools" / "packing_list.py"), "--max", str(t)], check=True)\n'
        "\n"
        "def thumbs():\n"
        '    os.system("convert in.png out.jpg")\n'
        "\n"
        "def anything(cmd):\n"
        "    subprocess.run(cmd)\n"
    )})
    deps = by_id(scan(tmp_path))
    assert set(deps) == {"local-packing-list", "local-convert"}
    packing = deps["local-packing-list"]
    assert packing.name == "packing list" and refs(packing) == {"jobs.py:6"}   # named for what it runs (D23)
    assert packing.target.endswith("tools/packing_list.py")
    assert deps["local-convert"].name == "convert" and deps["local-convert"].command == ["convert"]
    assert deps["local-convert"].status == "confirmed"


def test_a_service_sdk_is_its_service_even_without_a_url(tmp_path):
    write(tmp_path, {"pay.py": "import stripe\n\nstripe.PaymentIntent.create(amount=500)\n"})
    dep = by_id(scan(tmp_path))["api-stripe"]
    assert dep.name == "Stripe" and dep.status == "confirmed" and refs(dep) == {"pay.py:1"}


def test_javascript_and_typescript_by_patterns(tmp_path):
    write(tmp_path, {"src/app.ts": (
        'import OpenAI from "openai";\n'
        'import { createClient } from "@supabase/supabase-js";\n'
        'const ai = new OpenAI({ baseURL: "https://openrouter.ai/api/v1" });\n'
        "const res = await fetch(`https://weather.test/today?city=${city}`);\n"
        "const key = process.env.WEATHER_KEY;\n"
        'spawn("ffmpeg", ["-i", file]);\n'
        "// docs: \"https://docs.elsewhere.test/guide\"\n"
    )})
    result = scan(tmp_path)
    deps = by_id(result)
    assert set(deps) == {"llm-openrouter", "api-supabase", "api-weather-test", "local-ffmpeg"}
    assert {"src/app.ts:1", "src/app.ts:3"} <= refs(deps["llm-openrouter"])
    assert refs(deps["api-supabase"]) == {"src/app.ts:2"}
    weather = deps["api-weather-test"]
    assert weather.status == "confirmed" and weather.target == "https://weather.test/today"
    assert refs(deps["local-ffmpeg"]) == {"src/app.ts:6"}
    assert [e.name for e in result.env_names] == ["WEATHER_KEY"]


def test_dart_by_patterns(tmp_path):
    write(tmp_path, {"lib/map.dart": (
        "import 'package:flutter_map/flutter_map.dart';\n"
        "import 'package:supabase_flutter/supabase_flutter.dart';\n"
        "final tiles = TileLayer(urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png');\n"
        "final r = await http.get(Uri.parse('https://overpass-api.de/api/interpreter'));\n"
        "const url = String.fromEnvironment('SUPABASE_URL');\n"
        "final route = Uri.https('routes.test', '/v1/drive');\n"
    )})
    result = scan(tmp_path)
    deps = by_id(result)
    assert set(deps) == {"api-osm-tiles", "api-overpass", "api-supabase", "api-routes-test"}
    assert refs(deps["api-supabase"]) == {"lib/map.dart:2"}
    assert deps["api-routes-test"].target == "https://routes.test/v1/drive"
    assert [e.name for e in result.env_names] == ["SUPABASE_URL"]


def test_coding_tool_folders_are_not_app_code_but_their_mcp_configs_are_read(tmp_path):
    write(tmp_path, {
        ".claude/skills/x/run.mjs": 'const r = await fetch("https://skills.tool.test/api/v1");\nexecSync("git status");\n',
        ".github/scripts/ci.js": 'fetch("https://ci.tool.test/api/report");\n',
        ".vscode/mcp.json": '{"servers": {"github": {"command": "npx", "args": ["github-mcp"]}}}\n',
        "app.py": "print('hi')\n",
    })
    deps = by_id(scan(tmp_path))
    assert set(deps) == {"mcp-github"} and deps["mcp-github"].scope == "dev_tool"


def test_a_www_page_the_app_opens_is_unconfirmed_even_through_uri_parse(tmp_path):
    write(tmp_path, {"lib/nav.dart": "launchUrl(Uri.parse('https://www.maps.test/dir/home'));\n"})
    assert by_id(scan(tmp_path))["api-www-maps-test"].status == "unconfirmed"


def test_a_target_stops_before_template_parts(tmp_path):
    write(tmp_path, {"lib/route.dart": (
        "final r = await http.get(Uri.parse('https://router.test/route/v1/driving/$path?overview=false'));\n"
        "TileLayer(urlTemplate: 'https://tiles.test/{z}/{x}/{y}.png');\n"
    )})
    deps = by_id(scan(tmp_path))
    assert deps["api-router-test"].target == "https://router.test/route/v1/driving/"
    assert deps["api-tiles-test"].target == "https://tiles.test/"


def test_many_addresses_target_the_shared_path_of_the_host_most_use(tmp_path):
    """D23: nine image URLs gave the first image as the address to check."""
    write(tmp_path, {"lib/places.dart": (
        "final page = Uri.https('commons.wikimedia.org', '/wiki/File:$name');\n"
        "final a = 'https://thumb.wikimedia.org/commons/thumb/9/97/Glass_house.jpg';\n"
        "final b = 'https://thumb.wikimedia.org/commons/thumb/d/d5/Cubbon_Park.jpg';\n"
        "final c = 'https://thumb.wikimedia.org/commons/thumbnails/x.jpg';\n"
    )})
    assert by_id(scan(tmp_path))["api-wikimedia"].target == "https://thumb.wikimedia.org/commons/"


def test_evidence_is_capped_and_the_rest_are_counted(tmp_path):
    write(tmp_path, {"lib/data.dart": "".join(f"final p{i} = 'https://img.test/a{i}.jpg';\n" for i in range(40))})
    dep = by_id(scan(tmp_path))["api-img-test"]
    assert len(dep.evidence) == 10 and dep.places == 40


def test_in_a_git_repo_ignored_files_docs_and_tests_are_not_read(tmp_path):
    write(tmp_path, {
        ".gitignore": "generated/\n",
        "generated/client.py": 'URL = "https://ignored.test/api/v1"\n',
        "README.md": "Calls `https://readme.test/api/v1`.\n",
        "tests/test_app.py": 'URL = "https://fixture.test/api/v1"\n',
        "app.py": 'URL = "https://real.test/api/v1"\n',
    })
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert set(by_id(scan(tmp_path))) == {"api-real-test"}


def test_an_installed_but_unused_service_sdk_is_an_unconfirmed_hint(tmp_path):
    write(tmp_path, {
        "requirements.txt": "httpx>=0.27\nstripe==9.1  # payments, later\n",
        "package.json": '{"dependencies": {"@supabase/supabase-js": "^2.0.0", "left-pad": "1.0.0"}}\n',
        "pubspec.yaml": "name: app\ndependencies:\n  flutter:\n    sdk: flutter\n  google_generative_ai: ^0.4.0\n",
        "app.py": "print('hi')\n",
    })
    deps = by_id(scan(tmp_path))
    assert set(deps) == {"api-stripe", "api-supabase", "llm-gemini"}
    assert {d.status for d in deps.values()} == {"unconfirmed"}
    assert refs(deps["api-stripe"]) == {"requirements.txt:2"}
    assert refs(deps["api-supabase"]) == {"package.json:1"}
    assert refs(deps["llm-gemini"]) == {"pubspec.yaml:5"}


def test_ids_are_stable_across_scans():
    first, second = scan(TRIP_PLANNER), scan(TRIP_PLANNER)
    assert [d.id for d in first.dependencies] == [d.id for d in second.dependencies]


def test_a_known_service_is_named_and_its_hosts_merge(tmp_path):
    write(tmp_path, {"images.py": (
        'THUMB = "https://upload.wikimedia.org/a.jpg"\n'
        'PAGE = "https://commons.wikimedia.org/wiki/File:A.jpg"\n'
    )})
    deps = by_id(scan(tmp_path))
    assert set(deps) == {"api-wikimedia"}
    dep = deps["api-wikimedia"]
    assert dep.name == "Wikimedia" and dep.catalog == "wikimedia" and dep.status == "confirmed"
    assert dep.targets == ["https://upload.wikimedia.org/a.jpg", "https://commons.wikimedia.org/wiki/File:A.jpg"]


# --- the sample app: the scan must find exactly what its README lists -----------------------------------

def test_the_trip_planner_scan_matches_its_readme(no_network):
    result = scan(TRIP_PLANNER)
    deps = by_id(result)
    assert set(deps) == set(TRIP_PLANNER_DEPENDENCIES)
    for dep_id, expected in TRIP_PLANNER_DEPENDENCIES.items():
        assert expected <= refs(deps[dep_id]), dep_id
        assert deps[dep_id].status == "confirmed", dep_id
    assert {d.scope for d in result.dependencies} == {"app"}
    assert deps["api-wikipedia"].via == "mcp-fetch"
    assert deps["llm-ollama"].model == "llama3.1:8b" and deps["llm-ollama"].target == "localhost:11434"
    assert {e.name for e in result.env_names} == {"OLLAMA_BASE_URL", "PLANNER_MODEL", "OLLAMA_API_KEY",
                                                       "CURRENCY_API_URL"}


def test_the_planted_fake_key_is_never_in_the_result(no_network):
    dump = scan(TRIP_PLANNER).model_dump_json()
    assert "AIzaFAKE" not in dump
    assert "[REDACTED]" in dump   # its line is inside the Google Maps excerpt, masked


# --- found in review --------------------------------------------------------------------------------------

def test_a_remote_mcp_server_keeps_no_credentials_or_query(tmp_path):
    write(tmp_path, {".mcp.json": '{"mcpServers": {"crm": {"url": "https://bot:s3cretpass@mcp.crm.test/sse?token=abc"}}}',
                     "app.py": "print('hi')\n"})
    dump = scan(tmp_path).model_dump_json()
    assert "s3cretpass" not in dump and "bot:" not in dump and "token=abc" not in dump
    assert by_id(scan(tmp_path))["mcp-crm"].target == "https://mcp.crm.test/sse"


def test_only_a_real_call_is_labelled_as_one(tmp_path):
    write(tmp_path, {"app.py": (
        'MAP = "https://maps.tiles.test/api/static"\n'
        'def link(c):\n'
        '    return f"{MAP}?center={c}"\n'
    )})
    texts = {e.ref: e.text for e in by_id(scan(tmp_path))["api-maps-tiles-test"].evidence}
    assert texts["app.py:3"] == "uses the address" and texts["app.py:1"] == "the address"


def test_via_only_when_a_host_is_reached_only_through_an_mcp_server(tmp_path):
    write(tmp_path, {".mcp.json": MCP_CONFIG, "tools.py": (
        "from mcp import ClientSession\n"
        'SERVERS = ".mcp.json"\n'
        'async def a(): return await call("fetch", "fetch", {"url": "https://en.wikipedia.org/wiki/X"})\n'
        'def b(client): return client.post("https://en.wikipedia.org/w/api.php")\n'
    )})
    assert by_id(scan(tmp_path))["api-wikipedia"].via is None   # also called directly


def test_naming_one_server_makes_the_whole_config_the_apps(tmp_path):
    write(tmp_path, {".mcp.json": MCP_CONFIG, "tools.py": (
        "from mcp import ClientSession\n"
        'async def t(): return await call("time", "get_current_time", {})\n'
    )})
    deps = by_id(scan(tmp_path))
    assert deps["mcp-time"].scope == deps["mcp-fetch"].scope == "app"


def test_env_names_belong_to_the_whole_statement(tmp_path):
    write(tmp_path, {"llm.py": (
        "import os\n"
        "from openai import OpenAI\n"
        "client = OpenAI(\n"
        '    base_url="https://api.openai.com/v1",\n'
        '    api_key=os.environ["OPENAI_API_KEY"],\n'
        ")\n"
    )})
    assert by_id(scan(tmp_path))["llm-openai"].env_names == ["OPENAI_API_KEY"]


def test_a_dict_get_and_a_regex_exec_are_not_calls(tmp_path):
    write(tmp_path, {
        "app.py": 'CACHE = {}\nURL = "https://data.store.test/items"\ndef f(): return CACHE.get(URL)\n',
        "lib/x.js": "const m = /a(b)/.exec('abc');\nconst n = pattern.exec(\"zzz\");\n",
    })
    deps = by_id(scan(tmp_path))
    assert set(deps) == {"api-data-store-test"} and deps["api-data-store-test"].status == "unconfirmed"


def test_mcp_servers_started_from_code(tmp_path):
    write(tmp_path, {
        "agent.py": (
            "from mcp import StdioServerParameters\n"
            'params = StdioServerParameters(command="uvx", args=["mcp-server-git", "--repository", "."])\n'
        ),
        "src/agent.ts": 'const t = new StdioClientTransport({ command: "npx", args: ["-y", "@acme/notes-mcp"] });\n',
    })
    deps = by_id(scan(tmp_path))
    assert deps["mcp-mcp-server-git"].command == ["uvx", "mcp-server-git", "--repository", "."]
    assert refs(deps["mcp-mcp-server-git"]) == {"agent.py:2"} and deps["mcp-mcp-server-git"].scope == "app"
    assert refs(deps["mcp-acme-notes-mcp"]) == {"src/agent.ts:1"}


def test_litellm_is_resolved_by_its_model_prefix(tmp_path):
    write(tmp_path, {"bot.py": 'import litellm\nlitellm.completion(model="anthropic/claude-sonnet", messages=[])\n'})
    dep = by_id(scan(tmp_path))["llm-claude"]
    assert dep.model == "anthropic/claude-sonnet" and {"bot.py:1", "bot.py:2"} <= refs(dep)


def test_fake_data_and_test_files_are_ignored_wherever_they_are(tmp_path):
    """D23: a real repo's lib/dev/fake_recommendations.dart showed up as a dependency."""
    write(tmp_path, {
        "lib/dev/fake_recommendations.dart": "final a = 'https://img.fake.test/a.jpg';\n",
        "lib/dev/app_config.dart": "final api = Uri.https('api.real.test', '/v1');\n",
        "src/mock_server.ts": "fetch('https://mock.test/api/v1');\n",
        "src/client.test.ts": "fetch('https://spec.test/api/v1');\n",
        "lib/route_test.dart": "http.get(Uri.parse('https://dart-test.test/api/v1'));\n",
        "app/test_jobs.py": 'URL = "https://pytest.test/api/v1"\n',
        "web/__mocks__/api.js": "fetch('https://jest.test/api/v1');\n",
        "fixtures/data.py": 'URL = "https://fixture.test/api/v1"\n',
        "app/contest.py": 'URL = "https://contest.test/api/v1"\n',
    })
    result = scan(tmp_path)
    assert set(by_id(result)) == {"api-api-real-test", "api-contest-test"}
    assert result.skipped["ignored"] == 7


def test_binary_and_ignored_files_are_counted_not_read(tmp_path):
    write(tmp_path, {"app.py": 'URL = "https://api.real.test/v1"\n', "README.md": "x\n", "tests/t.py": "x\n"})
    (tmp_path / "blob.py").write_bytes(b"\x00\x01binary https://api.binary.test/v1")
    result = scan(tmp_path)
    assert set(by_id(result)) == {"api-api-real-test"}
    assert result.skipped["binary"] == 1 and result.skipped["ignored"] == 2


def test_evidence_excerpts_mask_credentials_queries_and_secret_named_values(tmp_path):
    write(tmp_path, {"app.py": (
        'CRM_TOKEN = "plainsecretvalue99"\n'
        'db_password: str = "hunter2hunter2"\n'
        'URL = "https://admin:pw12345678@api.crm.test/v1/items?api_key=zzzunknownshape"\n'
        "import httpx\n"
        "httpx.get(URL)\n"
    )})
    dump = scan(tmp_path).model_dump_json()
    for secret in ("plainsecretvalue99", "hunter2hunter2", "pw12345678", "zzzunknownshape"):
        assert secret not in dump, secret
    assert "api.crm.test" in dump   # the dependency itself is still found
