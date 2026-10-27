"""Offline CLI presentation, compatibility and leak checks (D41)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from rich.text import Text

from flowforge import cli, cli_ui, settings
from flowforge.projects import Projects
from flowforge.scan import scan
from flowforge.security.keystore import KeyStore
from flowforge.storage import Storage

FAKE = "sk_test_FAKEFAKE12345678"


class Output(io.StringIO):
    def __init__(self, tty: bool = True, encoding: str = "utf-8") -> None:
        super().__init__()
        self.tty = tty
        self.codec = encoding

    @property
    def encoding(self) -> str:
        return self.codec

    def isatty(self) -> bool:
        return self.tty


@pytest.fixture
def project(tmp_path, monkeypatch):
    folder = tmp_path / "shop"
    folder.mkdir()
    (folder / "app.py").write_text(
        'import os\nimport httpx\nKEY = os.environ["SHOP_TOKEN"]\n'
        'OTHER = os.environ["OTHER_TOKEN"]\n'
        f'EMBEDDED = "{FAKE}"\n'
        'httpx.get("http://api.shop.test/v1")\n', encoding="utf-8")
    result = scan(folder)
    registry = Projects()
    project = registry.add(folder)
    registry.touch(project.id)
    Path(project.db).parent.mkdir(parents=True, exist_ok=True)
    db = Storage(Path(project.db))
    db.add_flow_version("deps", "accepted", {"nodes": [{"kind": "api"} for d in result.dependencies]}, {},
                        {"scan": result.model_dump(mode="json")}, "fixture")
    db.add_checks("run-1", [{"id": result.dependencies[0].id, "kind": "api", "status": "up",
                             "summary": "reachable", "latency_ms": 12}])
    db.conn.close()
    KeyStore(folder).add("SHOP_TOKEN", FAKE)
    monkeypatch.chdir(folder)
    return project, result


@pytest.mark.parametrize(("tty", "plain", "no_color", "encoding", "shown"), [
    (True, False, False, "utf-8", True), (False, False, False, "utf-8", False),
    (True, True, False, "utf-8", False), (True, False, True, "utf-8", False),
    (True, False, False, "cp1252", False),
])
def test_banner_visibility(monkeypatch, tty, plain, no_color, encoding, shown):
    monkeypatch.delenv("NO_COLOR", raising=False)
    if no_color:
        monkeypatch.setenv("NO_COLOR", "")
    output = Output(tty, encoding)
    monkeypatch.setattr(sys, "stdout", output)
    cli_ui.banner(cli_ui.console(plain))
    assert ("FlowForge" in output.getvalue()) == shown
    if plain or no_color or not tty:
        assert "\x1b" not in output.getvalue()


def test_status_projects_issues_and_keys(project, capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "240")
    registered, result = project
    for command in (["status"], ["projects"], ["issues", registered.id], ["key", "list"]):
        cli.main([*command, "--plain"])
        output = capsys.readouterr().out
        assert FAKE not in output and "\x1b" not in output
        if command[0] == "status":
            assert "reachable" in output and "Keys missing: 1" in output and "OTHER_TOKEN" in output
            assert f"Issues: {len(result.findings)}" in output
        elif command[0] == "projects":
            assert "shop" in output and "Dependencies" in output and "Keys missing" in output
        elif command[0] == "issues":
            assert all(f.title in output and f.ref in output and f.fix in output for f in result.findings)
        else:
            assert "SHOP_TOKEN" in output and "saved" in output and "missing" in output


def test_project_counts_reuse_dashboard_summary(project, monkeypatch):
    captured = []
    monkeypatch.setattr(cli_ui, "table", lambda out, title, columns, rows: captured.extend(rows))
    cli.main(["projects", "--plain"])
    assert captured[0][0] == "shop"
    assert captured[0][2:5] == [len(project[1].dependencies), len(project[1].findings), 1]


@pytest.mark.parametrize("explicit_json", [False, True])
def test_scan_keeps_exact_json(project, monkeypatch, explicit_json):
    registered, result = project
    output = Output(tty=explicit_json)
    monkeypatch.setattr(sys, "stdout", output)
    cli.main(["scan", registered.path, *(["--json"] if explicit_json else [])])
    assert output.getvalue() == json.dumps(result.model_dump(mode="json"), indent=2) + "\n"


def test_interactive_scan_and_plain_have_a_summary(project, monkeypatch):
    output = Output()
    monkeypatch.setattr(sys, "stdout", output)
    cli.main(["scan", project[0].path, "--plain"])
    assert "Dependencies" in output.getvalue() and "Issues" in output.getvalue()
    assert "\x1b" not in output.getvalue()


def test_help_lists_commands_and_shows_banner_on_tty(monkeypatch):
    output = Output()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.delenv("NO_COLOR", raising=False)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--help"])
    assert stopped.value.code == 0
    assert "███████" in Text.from_ansi(output.getvalue()).plain
    assert all(c in output.getvalue() for c in ("status", "projects", "issues", "check", "settings", "--plain"))


def test_no_args_still_starts_dashboard_with_banner(monkeypatch):
    import uvicorn

    output = Output()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.delenv("NO_COLOR", raising=False)
    start = Mock()
    monkeypatch.setattr(uvicorn, "run", start)
    monkeypatch.setattr(cli.threading, "Timer", Mock())
    cli.main([])
    start.assert_called_once()
    assert start.call_args.args == ("flowforge.main:app",)
    assert "███████" in Text.from_ansi(output.getvalue()).plain


def test_settings_are_local(capsys):
    settings.save({"welcome_done": True, "map_style": "metro"})
    cli.main(["settings"])
    output = capsys.readouterr().out
    assert "true" in output and "metro" in output and "Version" in output


def test_unknown_project_is_an_error(capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(["status", "unknown"])
    assert stopped.value.code == 2
    assert "No such project" in capsys.readouterr().err


def test_no_project_has_a_next_step(capsys):
    cli.main(["status"])
    assert "flowforge --repo ." in capsys.readouterr().out


def test_selection_prefers_current_folder_then_last_opened(project, tmp_path, monkeypatch, capsys):
    other = tmp_path / "other"
    other.mkdir()
    registered = Projects().add(other)
    cli.main(["status"])
    assert "shop" in capsys.readouterr().out
    monkeypatch.chdir(tmp_path)
    cli.main(["status"])
    assert "shop" in capsys.readouterr().out
    cli.main(["status", registered.id])
    assert "No saved scan" in capsys.readouterr().out
    assert not Path(registered.db).exists()


def test_check_only_prints_plan_and_does_not_start_mcp(project, monkeypatch, capsys):
    import socket

    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    folder = Path(project[0].path)
    (folder / ".mcp.json").write_text('{"mcpServers":{"demo":{"command":"never-execute-me"}}}')
    result = scan(folder)
    db = Storage(Path(project[0].db))
    db.add_flow_version("deps", "accepted", {"nodes": []}, {}, {"scan": result.model_dump(mode="json")}, "fixture")
    db.conn.close()
    cli.main(["check"])
    output = capsys.readouterr().out
    assert "never-execute-me" in output and "need your yes" in output
    assert "run checks from the dashboard" in output


@pytest.mark.parametrize("command", [
    ["status"], ["projects"], ["issues"], ["check"], ["settings"], ["key", "list"],
    ["scan", "."], ["scan", ".", "--json"], ["--help"], ["--version"],
    ["serve", "--help"], ["mcp", "--help"], ["run", "--help"], ["lock", "--help"],
])
def test_commands_work_in_cp1252_pipes(project, command):
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "COLUMNS": "160"}
    run = subprocess.run([sys.executable, "-m", "flowforge.cli", *command],
                         capture_output=True, env=env, encoding="cp1252")
    assert run.returncode == 0, run.stderr
    assert FAKE not in run.stdout + run.stderr
    assert "\x1b" not in run.stdout
    if command[0] == "scan":
        expected = json.dumps(scan(Path(project[0].path)).model_dump(mode="json"), indent=2) + "\n"
        assert run.stdout == expected


def test_cp1252_replaces_unencodable_user_text(monkeypatch):
    output = Output(encoding="cp1252", tty=False)
    monkeypatch.setattr(sys, "stdout", output)
    cli_ui.table(cli_ui.console(), "Projects", ["Name"], [["shop 🛒"]])
    output.getvalue().encode("cp1252")
    assert "+" in output.getvalue() and "🛒" not in output.getvalue()


def test_project_commands_never_read_saved_key_values(project, monkeypatch, capsys):
    monkeypatch.setattr(KeyStore, "env", Mock(side_effect=AssertionError("must read names only")))
    for command in ("status", "projects", "issues", "check", "settings"):
        cli.main([command])
        assert FAKE not in capsys.readouterr().out


def test_plain_does_not_consume_the_child_programs_flags(monkeypatch):
    child = Mock()
    monkeypatch.setattr(cli, "run_with_keys", child)
    cli.main(["--plain", "run", "--", "python", "app.py", "--plain"])
    child.assert_called_once_with(["--", "python", "app.py", "--plain"])


def test_mcp_routing_stays_quiet(monkeypatch, capsys):
    server = Mock()
    monkeypatch.setattr(cli, "serve_agent", server)
    cli.main(["mcp", "--plain"])
    server.assert_called_once_with(None, None)
    assert capsys.readouterr().out == ""


def test_a_map_made_before_projects_is_a_project_for_the_cli_too(tmp_path, monkeypatch, capsys):
    """Like the dashboard at start (D39): the database you had before projects, and the folder it maps, become a
    project. Before this, the CLI said "No projects yet" until the dashboard had run once."""
    from flowforge.projects import Projects
    from flowforge.storage import Storage

    app = tmp_path / "travel-app"
    app.mkdir()
    old = tmp_path / "flowforge.db"
    Storage(old).set_setting("repo_path", str(app.resolve()))
    monkeypatch.setenv("FLOWFORGE_DB", str(old))
    cli.main(["projects", "--plain"])
    assert "travel-app" in capsys.readouterr().out
    [project] = Projects().list()
    assert Path(project.db) == old.resolve() and Path(project.path) == app.resolve()
    cli.main(["projects", "--plain"])   # listed once, not again
    assert len(Projects().list()) == 1


def test_no_old_map_means_no_project(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "nothing.db"))
    cli.main(["status", "--plain"])
    assert "No projects yet" in capsys.readouterr().out
    assert not (tmp_path / "nothing.db").exists()   # looking doesn't create a database


def test_an_old_map_in_a_folder_with_odd_characters_is_still_found(tmp_path, monkeypatch, capsys):
    """# and % mean something in a SQLite address; the path is quoted (Codex review)."""
    from flowforge.projects import Projects, adopt_existing
    from flowforge.storage import Storage

    odd = tmp_path / "my#app 50%"
    odd.mkdir()
    old = odd / "flowforge.db"
    Storage(old).set_setting("repo_path", str(odd.resolve()))
    monkeypatch.setenv("FLOWFORGE_DB", str(old))
    assert adopt_existing() is not None and len(Projects().list()) == 1
