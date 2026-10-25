""""Add to code" (D44): FlowForge finds where a key goes, and one click puts it into the app: the Vault, the code read,
and the hidden git-ignored file the app reads. Never the value in a code file, an answer or a log. Fake keys only."""

import json
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from flowforge.security.finders import spots_in
from flowforge.security.keystore import KeyStore
from flowforge.security.wire import CantAdd, add_to_code, key_spots

FAKE = "sk_test_FAKEFAKE12345678"
OTHER = "rzp_test_FAKE1234567"
RUN_CONFIG = """<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="main.dart" type="FlutterRunConfigurationType" factoryName="Flutter">
    <option name="filePath" value="$PROJECT_DIR$/lib/main.dart" />
    <method />
  </configuration>
</component>
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git/" not in
            p.as_posix()}


def code_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.suffix in (".py", ".dart", ".js", ".ts"))


def spot(root: Path, name: str):
    found = [s for s in key_spots(root) if s.name == name]
    assert len(found) == 1, found
    return found[0]


# the finder, one file at a time

def test_spots_in_a_dart_file():
    text = textwrap.dedent("""\
        const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');
        const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
        const apiKey = "ENTER KEY HERE";
        final token = '';
        const title = "Trips";
        final stripeKey = "sk_test_FAKEFAKE12345678";
    """)
    got = {(s.line, s.kind, s.name) for s in spots_in(text, "dart")}
    assert got == {(1, "reads", "SUPABASE_ANON_KEY"), (3, "placeholder", "API_KEY"), (4, "placeholder", "TOKEN"),
                   (6, "open", "STRIPE_KEY")}   # SUPABASE_URL isn't a key; a title isn't a spot
    assert all(FAKE not in repr(s) for s in spots_in(text, "dart"))


def test_a_string_built_from_values_or_a_bare_key_is_not_a_spot():
    """Found on Vishwa's Flutter app: a route's cache key built from coordinates isn't an API key."""
    text = textwrap.dedent("""\
        final key = '${trip.id}:${points.map((p) => '${p.latitude}').join(';')}';
        final cacheKey = 'route-$day';
        const key = "your-key";
        final apiKey = "${prefix}abc";
    """)
    assert spots_in(text, "dart") == []


def test_spots_in_python_and_typescript():
    py = 'import os\nA = os.environ["OPENAI_API_KEY"]\nB = os.getenv("HF_TOKEN")\napi_key = "your-api-key"\nn = "x"\n'
    assert {(s.line, s.kind, s.name) for s in spots_in(py, "python")} == {
        (2, "reads", "OPENAI_API_KEY"), (3, "reads", "HF_TOKEN"), (4, "placeholder", "API_KEY")}
    ts = 'const a = process.env.STRIPE_SECRET_KEY;\nconst b = import.meta.env.VITE_MAPS_KEY;\nconst secret = "xxxx";\n'
    assert {(s.line, s.kind, s.name) for s in spots_in(ts, "typescript")} == {
        (1, "reads", "STRIPE_SECRET_KEY"), (2, "reads", "VITE_MAPS_KEY"), (3, "placeholder", "SECRET")}


# your Smart Travel app's shape: the code already reads the key at build time

@pytest.fixture
def flutter(tmp_path):
    return write(tmp_path / "travel", {
        "pubspec.yaml": "name: travel\n",
        "lib/dev/app_config.dart": "const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');\n"
                                   "const mapsKey = \"ENTER KEY HERE\";\n",
        "lib/main.dart": "void main() {}\n",
        ".idea/runConfigurations/main_dart.xml": RUN_CONFIG,
        ".gitignore": "build/\n",
    })


def test_a_key_the_dart_code_already_reads_goes_to_the_run_config_not_the_code(flutter):
    before = (flutter / "lib/dev/app_config.dart").read_text()
    s = spot(flutter, "SUPABASE_ANON_KEY")
    assert (s.kind, s.ref, s.sink) == ("reads", "lib/dev/app_config.dart:1", "dart-defines")
    done = add_to_code(flutter, s.name, s.ref, s.check, FAKE)
    assert (flutter / "lib/dev/app_config.dart").read_text() == before   # nothing to rewrite
    defines = flutter / ".flowforge" / "dart-defines.json"
    assert json.loads(defines.read_text()) == {"SUPABASE_ANON_KEY": FAKE}
    if sys.platform != "win32":
        assert stat.S_IMODE(defines.stat().st_mode) == 0o600
    run = (flutter / ".idea/runConfigurations/main_dart.xml").read_text()
    assert run.count("--dart-define-from-file=.flowforge/dart-defines.json") == 1
    assert ".flowforge/" in (flutter / ".gitignore").read_text().splitlines()
    assert KeyStore(flutter).env() == {"SUPABASE_ANON_KEY": FAKE}
    deny = json.loads((flutter / ".claude" / "settings.local.json").read_text())["permissions"]["deny"]
    assert "Read(./.flowforge/**)" in deny
    assert FAKE not in json.dumps(done)
    assert "Run config" in " ".join(done["changed"])


def test_a_dart_placeholder_becomes_the_build_time_read(flutter):
    s = spot(flutter, "MAPS_KEY")
    assert s.kind == "placeholder"
    add_to_code(flutter, s.name, s.ref, s.check, OTHER)
    assert (flutter / "lib/dev/app_config.dart").read_text().splitlines()[1] == \
        "const mapsKey = String.fromEnvironment('MAPS_KEY');"
    assert json.loads((flutter / ".flowforge/dart-defines.json").read_text()) == {"MAPS_KEY": OTHER}
    assert OTHER.encode() not in code_bytes(flutter)


def test_a_second_key_keeps_the_first_and_the_run_config_once(flutter):
    for name, value in (("SUPABASE_ANON_KEY", FAKE), ("MAPS_KEY", OTHER)):
        s = spot(flutter, name)
        add_to_code(flutter, s.name, s.ref, s.check, value)
    assert json.loads((flutter / ".flowforge/dart-defines.json").read_text()) == {"SUPABASE_ANON_KEY": FAKE,
                                                                                    "MAPS_KEY": OTHER}
    assert (flutter / ".idea/runConfigurations/main_dart.xml").read_text().count("--dart-define-from-file") == 1
    assert (flutter / ".gitignore").read_text().count(".flowforge/") == 1


def test_a_final_dart_variable_gets_a_const_read(tmp_path):
    root = write(tmp_path / "app", {"pubspec.yaml": "name: a\n", "lib/keys.dart": "final token = '';\n"})
    s = spot(root, "TOKEN")
    add_to_code(root, s.name, s.ref, s.check, FAKE)
    assert (root / "lib/keys.dart").read_text() == "final token = const String.fromEnvironment('TOKEN');\n"


def test_vs_code_launch_json_gets_the_tool_arg(tmp_path):
    root = write(tmp_path / "app", {
        "pubspec.yaml": "name: a\n", "lib/k.dart": "const k = String.fromEnvironment('API_KEY');\n",
        ".vscode/launch.json": json.dumps({"version": "0.2.0", "configurations": [
            {"name": "app", "request": "launch", "type": "dart", "program": "lib/main.dart"},
            {"name": "web", "request": "launch", "type": "chrome"}]})})
    s = spot(root, "API_KEY")
    add_to_code(root, s.name, s.ref, s.check, FAKE)
    configs = json.loads((root / ".vscode/launch.json").read_text())["configurations"]
    assert configs[0]["toolArgs"] == ["--dart-define-from-file=.flowforge/dart-defines.json"]
    assert "toolArgs" not in configs[1]


# Python and Node with a .env loader

def test_a_python_placeholder_reads_the_env_and_the_key_goes_to_dotenv(tmp_path):
    root = write(tmp_path / "bot", {
        "app.py": '"""The bot."""\nfrom dotenv import load_dotenv\n\nload_dotenv()\nAPI_KEY = "your-api-key"\n',
        ".env": "# settings\nDEBUG=1\nAPI_KEY=old\n",
    })
    s = spot(root, "API_KEY")
    assert s.sink == ".env"
    add_to_code(root, s.name, s.ref, s.check, FAKE)
    app = (root / "app.py").read_text()
    assert 'API_KEY = os.environ["API_KEY"]' in app and "import os\n" in app
    assert app.index('"""The bot."""') < app.index("import os")
    env = (root / ".env").read_text().splitlines()
    assert env == ["# settings", "DEBUG=1", f"API_KEY={FAKE}"]   # other lines kept, the old line replaced
    assert ".env" in (root / ".gitignore").read_text().splitlines()


def test_an_open_key_is_hidden_with_one_click(tmp_path):
    root = write(tmp_path / "shop", {
        "pay.py": f'import os\nfrom dotenv import load_dotenv\n\nload_dotenv()\nSTRIPE_KEY = "{FAKE}"\n'})
    s = spot(root, "STRIPE_KEY")
    assert s.kind == "open"
    done = add_to_code(root, s.name, s.ref, s.check, None)   # the value comes from the code itself
    assert FAKE.encode() not in code_bytes(root)
    assert 'STRIPE_KEY = os.environ["STRIPE_KEY"]' in (root / "pay.py").read_text()
    assert f"STRIPE_KEY={FAKE}" in (root / ".env").read_text()
    assert KeyStore(root).env()["STRIPE_KEY"] == FAKE
    assert FAKE not in json.dumps(done)


def test_vite_code_reads_a_vite_name_from_env_local(tmp_path):
    root = write(tmp_path / "web", {
        "package.json": json.dumps({"devDependencies": {"vite": "^5.0.0"}}),
        "src/maps.ts": 'export const mapsKey = "";\n'})
    s = spot(root, "VITE_MAPS_KEY")   # Vite passes only VITE_ names to the browser
    assert s.sink == ".env.local"
    add_to_code(root, s.name, s.ref, s.check, FAKE)
    assert (root / "src/maps.ts").read_text() == "export const mapsKey = import.meta.env.VITE_MAPS_KEY;\n"
    assert (root / ".env.local").read_text() == f"VITE_MAPS_KEY={FAKE}\n"


def test_node_with_dotenv_reads_process_env(tmp_path):
    root = write(tmp_path / "api", {
        "package.json": json.dumps({"dependencies": {"dotenv": "^16.0.0", "express": "^4.0.0"}}),
        "server.js": "require('dotenv').config();\nconst express = require('express');\nconst apiKey = 'changeme';\n"})
    s = spot(root, "API_KEY")
    add_to_code(root, s.name, s.ref, s.check, FAKE)
    assert "const apiKey = process.env.API_KEY;" in (root / "server.js").read_text()
    assert f"API_KEY={FAKE}" in (root / ".env").read_text()


def test_a_value_needing_quotes_is_quoted_in_dotenv(tmp_path):
    root = write(tmp_path / "bot", {"app.py": "from dotenv import load_dotenv\nload_dotenv()\ntoken = ''\n"})
    s = spot(root, "TOKEN")
    add_to_code(root, s.name, s.ref, s.check, 'a b#c"d')
    from dotenv import dotenv_values

    assert dotenv_values(root / ".env")["TOKEN"] == 'a b#c"d'


# refusals: nothing half-done

def test_an_app_with_no_env_loader_gets_the_vault_only_and_says_why(tmp_path):
    root = write(tmp_path / "cli", {"tool.py": 'import os\nKEY = os.environ["OPENAI_API_KEY"]\n'})
    s = spot(root, "OPENAI_API_KEY")
    assert s.sink is None and "can't take keys from a file" in s.why_not
    before = snapshot(root)
    with pytest.raises(CantAdd):
        add_to_code(root, s.name, s.ref, s.check, FAKE)
    assert snapshot(root) == before and KeyStore(root).names() == []


def test_a_line_that_changed_since_the_page_showed_it_is_refused(flutter):
    s = spot(flutter, "MAPS_KEY")
    path = flutter / "lib/dev/app_config.dart"
    path.write_text(path.read_text().replace("ENTER KEY HERE", "PUT IT HERE"))
    before = snapshot(flutter)
    with pytest.raises(CantAdd, match="changed"):
        add_to_code(flutter, s.name, s.ref, s.check, FAKE)
    assert snapshot(flutter) == before and KeyStore(flutter).names() == []


def test_a_dotenv_file_git_already_tracks_is_refused(tmp_path):
    root = write(tmp_path / "bot", {"app.py": "from dotenv import load_dotenv\nload_dotenv()\ntoken = ''\n",
                                    ".env": "DEBUG=1\n"})
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], cwd=root, check=True)
    subprocess.run([*git, "add", "."], cwd=root, check=True)
    subprocess.run([*git, "commit", "-qm", "x"], cwd=root, check=True)
    s = spot(root, "TOKEN")
    before = snapshot(root)
    with pytest.raises(CantAdd, match="git"):
        add_to_code(root, s.name, s.ref, s.check, FAKE)
    assert snapshot(root) == before


def test_an_empty_value_is_refused(flutter):
    s = spot(flutter, "SUPABASE_ANON_KEY")
    with pytest.raises(CantAdd):
        add_to_code(flutter, s.name, s.ref, s.check, "   ")


# through the API: the Keys page's box

LOCAL = "http://127.0.0.1:8000"
HERE = ("127.0.0.1", 50000)


@pytest.fixture
def served(flutter, tmp_path, monkeypatch):
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(flutter))
    from fastapi.testclient import TestClient

    from flowforge import main

    return lambda: TestClient(main.app, base_url=LOCAL, client=HERE)


def test_the_keys_page_gets_each_keys_spot_and_no_command_with_a_placeholder(served):
    with served() as c:
        got = c.get("/keys").json()
    keys = {k["name"]: k for k in got["keys"]}
    assert keys["SUPABASE_ANON_KEY"]["spot"]["ref"] == "lib/dev/app_config.dart:1"
    assert keys["SUPABASE_ANON_KEY"]["spot"]["where"] == "your Run config"
    assert keys["MAPS_KEY"]["spot"]["kind"] == "placeholder"   # a spot the code doesn't read yet still shows
    assert "<" not in json.dumps(got)   # no "<how you start your app>" anywhere


def test_add_to_code_from_the_box(served, flutter):
    with served() as c:
        k = {k["name"]: k for k in c.get("/keys").json()["keys"]}["SUPABASE_ANON_KEY"]
        r = c.post("/keys/SUPABASE_ANON_KEY/add-to-code",
                   json={"value": FAKE, "ref": k["spot"]["ref"], "check": k["spot"]["check"]})
        assert r.status_code == 200, r.text
        assert FAKE not in r.text and "Vault" in r.json()["changed"]
        after = {k["name"]: k for k in c.get("/keys").json()["keys"]}["SUPABASE_ANON_KEY"]
        assert after["status"] == "saved" and after["in_app"] is True
    assert json.loads((flutter / ".flowforge/dart-defines.json").read_text())["SUPABASE_ANON_KEY"] == FAKE


def test_add_to_code_refuses_a_stale_spot_and_another_machine(served):
    with served() as c:
        k = {k["name"]: k for k in c.get("/keys").json()["keys"]}["MAPS_KEY"]
        body = {"value": FAKE, "ref": k["spot"]["ref"], "check": "0" * 16}
        stale = c.post("/keys/MAPS_KEY/add-to-code", json=body)
        assert stale.status_code == 409 and "changed" in stale.json()["detail"]
        body["check"] = k["spot"]["check"]
        evil = c.post("/keys/MAPS_KEY/add-to-code", json=body, headers={"host": "evil.test"})
        assert evil.status_code == 403


def test_example_data_is_never_rewritten(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    from fastapi.testclient import TestClient

    from flowforge import main

    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        r = c.post("/keys/OLLAMA_API_KEY/add-to-code", json={"value": FAKE, "ref": "config.py:30", "check": "x"})
    assert r.status_code == 409


async def test_the_agent_sees_where_each_key_goes_never_a_value(flutter, tmp_path):
    from mcp import Client

    from flowforge.agent import build_server
    from flowforge.storage import Storage

    s = spot(flutter, "SUPABASE_ANON_KEY")
    add_to_code(flutter, s.name, s.ref, s.check, FAKE)
    async with Client(build_server(flutter, Storage(tmp_path / "agent.db"))) as client:
        result = await client.call_tool("get_keys", {})
    text = result.content[0].text
    assert FAKE not in text
    keys = {k["name"]: k for k in json.loads(text)["keys"]}
    assert keys["MAPS_KEY"]["spot"]["ref"] == "lib/dev/app_config.dart:2"


def test_a_key_saved_before_goes_into_the_app_with_no_retyping(served, flutter):
    KeyStore(flutter).add("SUPABASE_ANON_KEY", FAKE)   # saved with the old box: in the Vault, not in the app
    with served() as c:
        k = {k["name"]: k for k in c.get("/keys").json()["keys"]}["SUPABASE_ANON_KEY"]
        assert k["status"] == "saved" and k["in_app"] is False
        r = c.post("/keys/SUPABASE_ANON_KEY/add-to-code", json={"ref": k["spot"]["ref"], "check": k["spot"]["check"]})
        assert r.status_code == 200, r.text
    assert json.loads((flutter / ".flowforge/dart-defines.json").read_text()) == {"SUPABASE_ANON_KEY": FAKE}
