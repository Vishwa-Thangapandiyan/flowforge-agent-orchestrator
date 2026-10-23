"""An installable package (D34): files found inside the package or the checkout, data kept outside the package, and
the agent's command matching how FlowForge was installed."""

import sys
from pathlib import Path

from flowforge import home
from flowforge.api import agent


def test_a_packaged_resource_wins_and_the_checkout_is_the_fallback(tmp_path):
    package, checkout = tmp_path / "pkg", tmp_path / "repo"
    (checkout / "frontend" / "dist").mkdir(parents=True)
    assert home.resource("dashboard", package, checkout) == checkout / "frontend" / "dist"
    (package / "_dashboard").mkdir(parents=True)
    assert home.resource("dashboard", package, checkout) == package / "_dashboard"
    assert home.resource("example", package, checkout) == checkout / "examples" / "trip-planner"


def test_this_checkout_finds_everything_it_ships():
    for name in ("example", "workflows", "classic"):
        assert home.resource(name).exists(), name
    assert (home.resource("example") / ".mcp.json").is_file()


def test_installed_the_database_lives_in_flowforge_home_not_in_the_package(tmp_path, monkeypatch):
    monkeypatch.delenv("FLOWFORGE_DB", raising=False)
    monkeypatch.setenv("FLOWFORGE_HOME", str(tmp_path / "ffhome"))
    monkeypatch.setattr(home, "IN_CHECKOUT", False)
    assert home.database_path() == tmp_path / "ffhome" / "flowforge.db"
    assert home.database_path(example=True) == tmp_path / "ffhome" / "example.db"
    monkeypatch.setattr(home, "IN_CHECKOUT", True)
    assert home.database_path() == home.CHECKOUT / "flowforge.db"
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "mine.db"))
    assert home.database_path() == tmp_path / "mine.db"


def test_the_agents_command_follows_how_flowforge_was_installed(monkeypatch):
    tail = ["mcp", "--repo", "/home/me/app", "--db", "/home/me/.flowforge/flowforge.db"]
    monkeypatch.setattr(home, "install_kind", lambda: "checkout")
    assert agent._command("/home/me/app", "/home/me/.flowforge/flowforge.db")[-5:] == tail
    assert "--directory" in agent._command("/home/me/app", "/home/me/.flowforge/flowforge.db")
    monkeypatch.setattr(home, "install_kind", lambda: "uvx")
    cmd = agent._command("/home/me/app", "/home/me/.flowforge/flowforge.db")
    assert Path(cmd[0]).stem.lower() == "uvx" and cmd[1] == f"flowforge=={home.version()}" and cmd[2:] == tail   # pinned (D31)
    monkeypatch.setattr(home, "install_kind", lambda: "pip")
    assert agent._command("/home/me/app", "/home/me/.flowforge/flowforge.db") == [sys.executable, "-m", "flowforge.cli", *tail]


def test_install_kind_reads_where_python_runs(monkeypatch):
    monkeypatch.setattr(home, "IN_CHECKOUT", False)
    monkeypatch.setattr(sys, "prefix", str(Path.home() / ".cache" / "uv" / "archive-v0" / "abc123"))
    assert home.install_kind() == "uvx"
    monkeypatch.setattr(sys, "prefix", "/home/me/venvs/tools")
    assert home.install_kind() == "pip"
    monkeypatch.setattr(home, "IN_CHECKOUT", True)
    assert home.install_kind() == "checkout"


def test_version_is_the_packages():
    assert home.version() == "0.1.0"


def test_the_first_launch_creates_the_data_folder(tmp_path):
    from flowforge.storage import Storage

    db = tmp_path / "not-yet" / "deeper" / "flowforge.db"
    Storage(db).set_setting("hello", "world")   # a fresh install: ~/.flowforge doesn't exist yet
    assert db.is_file()
