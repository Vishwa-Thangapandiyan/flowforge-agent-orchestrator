"""One install does everything (D50): the desktop app can put the `flowforge` command in your terminal, without
admin rights. macOS and Windows are exercised here with a fake home and a fake registry; nothing outside tmp."""

import os
import sys
from pathlib import Path

import pytest

from flowforge import terminal

LINE = 'export PATH="$HOME/.flowforge/cmd:$PATH"   # the flowforge command (FlowForge, D50)'


class FakeRegistry:
    """HKCU\\Environment's Path, as Windows keeps it."""

    def __init__(self, path: str | None):
        self.path = path
        self.broadcasts = 0

    def get_path(self) -> str | None:
        return self.path

    def set_path(self, value: str) -> None:
        self.path = value

    def broadcast(self) -> None:
        self.broadcasts += 1


@pytest.fixture
def mac(tmp_path):
    app = tmp_path / "Applications" / "FlowForge.app" / "Contents" / "MacOS" / "flowforge"
    app.parent.mkdir(parents=True)
    app.write_text("#!/bin/sh\n")
    home = tmp_path / "me"
    home.mkdir()
    (home / ".zprofile").write_text("export EDITOR=vim\n")
    return home, app


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin rights on Windows")
def test_macos_links_the_command_and_adds_its_folder_to_path_once(mac):
    home, app = mac
    for _ in range(2):   # twice: nothing doubles
        done = terminal.add(platform="darwin", home=home, exe=app, environ={"PATH": "/usr/bin"})
        assert done["added"] is True
    link = home / ".flowforge" / "cmd" / "flowforge"
    assert link.is_symlink() and Path(os.readlink(link)) == app
    zprofile = (home / ".zprofile").read_text()
    assert zprofile.startswith("export EDITOR=vim\n") and zprofile.count(LINE) == 1   # your lines kept
    assert (home / ".bash_profile").read_text().count(LINE) == 1
    assert "new terminal" in done["message"]


def test_windows_adds_the_apps_folder_to_your_user_path_once():
    exe = Path("C:/Program Files/FlowForge/flowforge.exe")
    reg = FakeRegistry(r"C:\Users\me\bin;%USERPROFILE%\.local\bin")
    for _ in range(2):
        terminal.add(platform="win32", exe=exe, registry=reg)
    parts = reg.path.split(";")
    assert parts[:2] == [r"C:\Users\me\bin", r"%USERPROFILE%\.local\bin"]   # what you had stays first
    assert [p for p in parts if "FlowForge" in p] == [str(exe.parent)]
    assert reg.broadcasts >= 1


def test_windows_with_no_user_path_yet():
    reg = FakeRegistry(None)
    terminal.add(platform="win32", exe=Path("C:/Program Files/FlowForge/flowforge.exe"), registry=reg)
    assert reg.path == str(Path("C:/Program Files/FlowForge"))


def test_linux_packages_already_have_it_and_an_appimage_says_what_to_do(tmp_path):
    rpm = terminal.add(platform="linux", exe=Path("/usr/bin/flowforge"), environ={})
    assert rpm["added"] is False and "already" in rpm["message"]
    appimage = terminal.add(platform="linux", exe=Path("/tmp/.mount_FlowFoXYZ/usr/bin/flowforge"),
                            environ={"APPIMAGE": "/home/me/FlowForge.AppImage"})
    assert appimage["added"] is False and ".rpm" in appimage["message"] and "npx" in appimage["message"]


def test_status_says_whether_flowforge_works_and_which_program_it_finds(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ours = bin_dir / ("flowforge.exe" if sys.platform == "win32" else "flowforge")
    ours.write_text("x")
    ours.chmod(0o755)
    got = terminal.status(platform=sys.platform, exe=ours, environ={"PATH": str(bin_dir)}, kind="desktop")
    assert got["available"] is True and got["works"] is True and got["ours"] is True
    none = terminal.status(platform=sys.platform, exe=ours, environ={"PATH": str(tmp_path / "empty")}, kind="desktop")
    assert none["works"] is False
    assert terminal.status(platform=sys.platform, exe=ours, environ={}, kind="pip")["available"] is False   # app only


def test_the_route_answers_only_the_desktop_app(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from flowforge import main

    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "e.db"))
    with TestClient(main.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 5000)) as c:
        assert c.get("/settings/terminal").json()["available"] is False   # a checkout isn't the desktop app
        assert c.post("/settings/terminal").status_code == 409


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin rights on Windows")
def test_macos_never_deletes_a_command_that_isnt_flowforges(mac, tmp_path):
    """Codex review: a file or link of your own at ~/.flowforge/cmd/flowforge stays, and the card says so."""
    home, app = mac
    cmd = home / ".flowforge" / "cmd"
    cmd.mkdir(parents=True)
    mine = cmd / "flowforge"
    mine.write_text("#!/bin/sh\necho mine\n")
    done = terminal.add(platform="darwin", home=home, exe=app, environ={})
    assert done["added"] is False and "isn't FlowForge's" in done["message"]
    assert mine.read_text() == "#!/bin/sh\necho mine\n"
    mine.unlink()
    elsewhere = tmp_path / "other-tool"
    elsewhere.write_text("x")
    mine.symlink_to(elsewhere)
    assert terminal.add(platform="darwin", home=home, exe=app, environ={})["added"] is False
    assert Path(os.readlink(mine)) == elsewhere


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin rights on Windows")
def test_macos_replaces_its_own_link_when_the_app_moved(mac, tmp_path):
    home, app = mac
    terminal.add(platform="darwin", home=home, exe=app, environ={})
    moved = tmp_path / "Elsewhere" / "FlowForge.app" / "Contents" / "MacOS" / "flowforge"
    moved.parent.mkdir(parents=True)
    moved.write_text("#!/bin/sh\n")
    assert terminal.add(platform="darwin", home=home, exe=moved, environ={})["added"] is True
    assert Path(os.readlink(home / ".flowforge" / "cmd" / "flowforge")) == moved
