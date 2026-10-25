"""Keys the coding agent never sees, end to end (D36): the dashboard's write-only box, the agent's `get_keys`, the
`flowforge key` and `flowforge run` commands, and a saved key found in no answer, row or log. Fake keys only."""

import json
import logging
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from flowforge import cli, main
from flowforge.agent import build_server
from flowforge.security.keystore import KeyStore
from flowforge.storage import Storage

FAKE = "sk_test_FAKEFAKE12345678"
OTHER = "rzp_test_FAKE1234567"
PLAIN = "plainvalue-FAKE-0000-1111"
LOCAL = "http://127.0.0.1:8000"   # the dashboard's own address: key writes come from this machine only   # no known key shape: only the redactor's memory of saved keys masks it
HERE = ("127.0.0.1", 50000)   # the caller's real address: this machine


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return root


@pytest.fixture
def shop(tmp_path):
    return write(tmp_path / "shop", {
        "pay.py": """
            import os
            import httpx

            STRIPE = os.environ["STRIPE_SECRET_KEY"]
            HOST = os.getenv("OLLAMA_HOST")

            def pay():
                return httpx.post("https://api.stripe.com/v1/charges", headers={"Authorization": STRIPE})
        """,
        "ai.py": """
            import os
            from openai import OpenAI

            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        """,
        ".env": f"OPENAI_API_KEY={OTHER}\n",
    })


@pytest.fixture
def real(tmp_path, monkeypatch, shop):
    db = tmp_path / "flowforge.db"
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(db))
    monkeypatch.setenv("FLOWFORGE_REPO", str(shop))
    return db


def by_name(keys):
    return {k["name"]: k for k in keys}


def test_the_map_lists_each_key_the_code_reads_with_its_status(real, shop):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        got = c.get("/keys").json()
    keys = by_name(got["keys"])
    assert set(keys) == {"STRIPE_SECRET_KEY", "OPENAI_API_KEY"}   # OLLAMA_HOST isn't a key
    assert keys["STRIPE_SECRET_KEY"]["status"] == "missing"
    assert keys["STRIPE_SECRET_KEY"]["ref"] == "pay.py:5"
    assert keys["STRIPE_SECRET_KEY"]["deps"] == ["api-stripe"]
    assert "key add STRIPE_SECRET_KEY --repo" in keys["STRIPE_SECRET_KEY"]["command"]
    assert keys["OPENAI_API_KEY"]["status"] == "env_file"
    assert "key import" in keys["OPENAI_API_KEY"]["command"]
    assert got["example"] is False and got["summary"] == {"missing": 1, "env_file": 1}


def test_a_key_saved_from_the_dashboard_is_never_sent_back(real, shop):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        r = c.put("/keys/STRIPE_SECRET_KEY", json={"value": FAKE})
        assert r.status_code == 200 and FAKE not in r.text
        assert r.json() == {"name": "STRIPE_SECRET_KEY", "status": "saved"}
        keys = by_name(c.get("/keys").json()["keys"])
        assert keys["STRIPE_SECRET_KEY"]["status"] == "saved" and keys["STRIPE_SECRET_KEY"]["command"] is None
    assert KeyStore(shop).env()["STRIPE_SECRET_KEY"] == FAKE


def test_the_box_takes_json_only_and_checks_the_name(real):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.put("/keys/STRIPE_SECRET_KEY", content=f"value={FAKE}",
                     headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 422
        assert c.put("/keys/STRIPE_SECRET_KEY", json={"value": FAKE, "extra": 1}).status_code == 422
        r = c.put("/keys/1BAD", json={"value": FAKE})
        assert r.status_code == 400 and FAKE not in r.text
        assert c.put("/keys/STRIPE_SECRET_KEY", json={"value": "  "}).status_code == 400


@pytest.mark.parametrize("headers", [
    {"host": "evil.test"},                                            # DNS rebinding: a site's name pointed at 127.0.0.1
    {"host": "127.0.0.1:8000", "origin": "http://evil.test"},         # another site's page
    {"host": "localhost:8000", "origin": "null"},
])
def test_only_the_dashboard_on_this_machine_can_save_or_forget_a_key(real, shop, headers):
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.put("/keys/STRIPE_SECRET_KEY", json={"value": FAKE}, headers=headers).status_code == 403
        assert c.delete("/keys/STRIPE_SECRET_KEY", headers=headers).status_code == 403
        for ok in ({"host": "localhost:8000", "origin": "http://localhost:5173"}, {"host": "[::1]:8000"}):
            assert c.put("/keys/STRIPE_SECRET_KEY", json={"value": FAKE}, headers=ok).status_code == 200
    assert KeyStore(shop).names() == ["STRIPE_SECRET_KEY"]


def test_delete_forgets_a_key(real, shop):
    KeyStore(shop).add("STRIPE_SECRET_KEY", FAKE)
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.delete("/keys/STRIPE_SECRET_KEY").json() == {"name": "STRIPE_SECRET_KEY", "removed": True}
        assert c.delete("/keys/STRIPE_SECRET_KEY").json()["removed"] is False
    assert KeyStore(shop).names() == []


def test_example_mode_saves_keys_for_the_example_folder(tmp_path, monkeypatch):
    """D37: the demo works, so a key saves; it belongs to the example's folder, never to yours."""
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.get("/keys").json()["example"] is True
        assert c.put("/keys/OLLAMA_API_KEY", json={"value": FAKE}).status_code == 200
        keys = by_name(c.get("/keys").json()["keys"])
        assert keys["OLLAMA_API_KEY"]["status"] == "saved"
        assert c.delete("/keys/OLLAMA_API_KEY").json()["removed"] is True


def test_no_folder_means_no_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.delenv("FLOWFORGE_REPO", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "empty.db"))
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        assert c.get("/keys").json()["keys"] == []
        assert c.put("/keys/A_KEY", json={"value": FAKE}).status_code == 409


def test_a_saved_key_appears_in_no_answer_row_or_log(real, shop, caplog):
    """The leak walk (§6.5): even a value of no known shape is masked once it is saved."""
    KeyStore(shop).add("PLAIN_TOKEN", PLAIN)
    write(shop, {"leak.py": f'import httpx\nhttpx.get("https://api.example.test/{PLAIN}")\n'})
    caplog.set_level(logging.DEBUG)
    with TestClient(main.app, base_url=LOCAL, client=HERE) as c:
        c.put("/keys/STRIPE_SECRET_KEY", json={"value": FAKE})
        logging.getLogger("flowforge.test").warning("leaked %s and %s", PLAIN, FAKE)
        answers = [c.get(r.path).text for r in main.app.routes
                   if "GET" in getattr(r, "methods", ()) and "{" not in r.path]
    for value in (FAKE, PLAIN):
        assert all(value not in text for text in answers), value
        assert value.encode() not in real.read_bytes()
        assert value not in caplog.text
    assert PLAIN not in (Path(KeyStore(shop).home) / "keys.json").read_text()


async def test_the_agent_gets_names_and_commands_never_values(shop, tmp_path):
    KeyStore(shop).add("OPENAI_API_KEY", OTHER)
    async with Client(build_server(shop, Storage(tmp_path / "agent.db"))) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools["get_keys"].annotations.read_only_hint is True
        assert "value" not in json.dumps(tools["get_keys"].input_schema)
        result = await client.call_tool("get_keys", {})
    text = result.content[0].text
    assert OTHER not in text
    keys = by_name(json.loads(text)["keys"])
    assert keys["OPENAI_API_KEY"]["status"] == "saved"
    assert keys["STRIPE_SECRET_KEY"]["status"] == "missing"
    assert "key add STRIPE_SECRET_KEY" in keys["STRIPE_SECRET_KEY"]["command"]


async def test_the_agents_server_never_reads_a_value(shop, tmp_path, monkeypatch):
    KeyStore(shop).add("OPENAI_API_KEY", OTHER)

    def refuse(self):
        raise AssertionError("the MCP server read a key's value")

    monkeypatch.setattr(KeyStore, "env", refuse)
    async with Client(build_server(shop, Storage(tmp_path / "agent.db"))) as client:
        for tool in ("get_keys", "get_map", "get_security_findings"):
            assert not (await client.call_tool(tool, {})).is_error


# the CLI

def test_key_add_reads_the_value_hidden_and_never_prints_it(shop, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": FAKE)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    cli.main(["key", "add", "STRIPE_SECRET_KEY", "--repo", str(shop)])
    out = capsys.readouterr()
    assert FAKE not in out.out + out.err and "STRIPE_SECRET_KEY" in out.out
    assert KeyStore(shop).env() == {"STRIPE_SECRET_KEY": FAKE}


def test_key_add_reads_a_piped_value(shop, monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(FAKE + "\n"))
    cli.main(["key", "add", "STRIPE_SECRET_KEY", "--repo", str(shop)])
    assert KeyStore(shop).env() == {"STRIPE_SECRET_KEY": FAKE}


def test_key_add_refuses_a_bad_name_before_asking(shop, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("asked for a value"))
    with pytest.raises(SystemExit) as e:
        cli.main(["key", "add", "not-a-name", "--repo", str(shop)])
    assert e.value.code == 2


def test_key_list_shows_statuses_never_values(shop, capsys):
    KeyStore(shop).add("STRIPE_SECRET_KEY", FAKE)
    cli.main(["key", "list", "--repo", str(shop)])
    out = capsys.readouterr().out
    assert FAKE not in out and OTHER not in out
    lines = {line.split()[0]: line for line in out.splitlines() if line.strip() and line.split()[0].isupper()}
    assert "saved" in lines["STRIPE_SECRET_KEY"] and "in .env" in lines["OPENAI_API_KEY"]


def test_key_import_and_remove(shop, capsys):
    cli.main(["key", "import", "--repo", str(shop)])
    assert KeyStore(shop).names() == ["OPENAI_API_KEY"]
    out = capsys.readouterr().out
    assert OTHER not in out and "delete" in out.lower()
    cli.main(["key", "remove", "OPENAI_API_KEY", "--repo", str(shop)])
    assert KeyStore(shop).names() == []


def test_run_starts_your_app_with_the_keys(shop, tmp_path):
    KeyStore(shop).add("STRIPE_SECRET_KEY", FAKE)
    out = tmp_path / "seen.txt"
    script = f"import os, pathlib; pathlib.Path({str(out)!r}).write_text(os.environ['STRIPE_SECRET_KEY'])"
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--repo", str(shop), "--", sys.executable, "-c", script])
    assert e.value.code == 0 and out.read_text() == FAKE


def test_run_passes_the_exit_code_and_uses_no_shell(shop, tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--repo", str(shop), "--", sys.executable, "-c", "import sys; sys.exit(7)"])
    assert e.value.code == 7
    marker = tmp_path / "shell-ran"
    with pytest.raises(SystemExit):
        cli.main(["run", "--repo", str(shop), "--", sys.executable, "-c", "pass", f"; touch {marker}"])
    assert not marker.exists()


def test_run_needs_a_command(shop):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--repo", str(shop)])
    assert e.value.code == 2


def test_the_key_commands_work_where_output_is_not_utf8(shop):
    """Windows writes a pipe in cp1252: a "✓" in the output made `flowforge key add` fail there (CI smoke test)."""
    import os
    import subprocess

    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    for args, given in [(["add", "STRIPE_SECRET_KEY"], FAKE + "\n"), (["list"], ""), (["import"], ""),
                        (["remove", "STRIPE_SECRET_KEY"], "")]:
        run = subprocess.run([sys.executable, "-m", "flowforge.cli", "key", *args, "--repo", str(shop)], input=given,
                             capture_output=True, text=True, env=env, encoding="cp1252")
        assert run.returncode == 0, (args, run.stderr[-400:])
        assert FAKE not in run.stdout + run.stderr


def test_run_fills_masks_in_the_command_too(shop, tmp_path):
    """D43: `flowforge run -- app --key=ffkey://NAME` gets the value, like run_app."""
    KeyStore(shop).add("STRIPE_SECRET_KEY", FAKE)
    out = tmp_path / "seen.txt"
    script = f"import sys, pathlib; pathlib.Path({str(out)!r}).write_text(sys.argv[1])"
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--repo", str(shop), "--", sys.executable, "-c", script, "ffkey://STRIPE_SECRET_KEY"])
    assert e.value.code == 0 and out.read_text() == FAKE


def test_run_refuses_a_mask_for_a_key_that_isnt_saved(shop, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--repo", str(shop), "--", sys.executable, "-c", "pass", "ffkey://NOT_SAVED"])
    assert e.value.code == 2 and "NOT_SAVED" in capsys.readouterr().err
