"""One install does everything (D50): the desktop app's program is the `flowforge` command, and Settings can put it in
your terminal without admin rights. Linux packages (.deb, .rpm) already install it in /usr/bin; on macOS a link in
~/.flowforge/cmd plus one PATH line in your shell profiles; on Windows the app's folder in your user Path."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Protocol

CMD_DIR = Path(".flowforge") / "cmd"   # under your home folder (macOS)
PROFILE_LINE = 'export PATH="$HOME/.flowforge/cmd:$PATH"   # the flowforge command (FlowForge, D50)'
PROFILES = (".zprofile", ".bash_profile")   # zsh is macOS's shell; bash for those who switched back


class Registry(Protocol):
    def get_path(self) -> str | None: ...
    def set_path(self, value: str) -> None: ...
    def broadcast(self) -> None: ...


class _WindowsRegistry:
    """HKCU\\Environment\\Path: your own Path, no admin rights needed."""

    def get_path(self) -> str | None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                return str(winreg.QueryValueEx(key, "Path")[0])
            except FileNotFoundError:
                return None

    def set_path(self, value: str) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)

    def broadcast(self) -> None:
        """Tell running programs the environment changed, so new terminals see it (best effort)."""
        try:
            import ctypes

            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)  # type: ignore[attr-defined]
        except Exception:
            pass


def _command_name(platform: str) -> str:
    return "flowforge.exe" if platform == "win32" else "flowforge"


def _on_path(platform: str, environ: dict[str, str]) -> Path | None:
    found = shutil.which(_command_name(platform), path=environ.get("PATH", ""))
    return Path(found) if found else None


def status(*, platform: str = sys.platform, exe: Path | None = None, environ: dict[str, str] | None = None,
           kind: str | None = None) -> dict[str, Any]:
    """Can the desktop app add the command (only it can), does `flowforge` work, and is it this app's program?"""
    from flowforge.home import install_kind

    exe = Path(exe or sys.executable)
    environ = dict(os.environ if environ is None else environ)
    found = _on_path(platform, environ)
    ours = found is not None and _same(found, exe)
    return {"available": (kind or install_kind()) == "desktop", "works": found is not None, "ours": ours,
            "finds": str(found) if found else None, "system": _system(platform)}


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _system(platform: str) -> str:
    return {"win32": "windows", "darwin": "macos"}.get(platform, "linux")


def add(*, platform: str = sys.platform, exe: Path | None = None, home: Path | None = None,
        environ: dict[str, str] | None = None, registry: Registry | None = None) -> dict[str, Any]:
    """Put `flowforge` in new terminals. Returns {added, message}. Safe to repeat: nothing is added twice."""
    exe = Path(exe or sys.executable)
    environ = dict(os.environ if environ is None else environ)
    if platform == "win32":
        return _add_windows(exe, registry or _WindowsRegistry())
    if platform == "darwin":
        return _add_macos(exe, Path(home or Path.home()))
    if environ.get("APPIMAGE"):
        return {"added": False, "message": "The AppImage has no fixed place to link to. Install the .rpm or .deb "
                                           "instead, or use npx flowforge-map."}
    return {"added": False, "message": f"flowforge is already a command: the app installed it ({exe})."}


def _add_windows(exe: Path, registry: Registry) -> dict[str, Any]:
    folder = str(exe.parent)
    current = registry.get_path() or ""
    parts = [p for p in current.split(";") if p]
    if not any(os.path.normcase(os.path.expandvars(p.rstrip("\\/"))) == os.path.normcase(folder.rstrip("\\/"))
               for p in parts):
        registry.set_path(";".join([*parts, folder]))
        registry.broadcast()
    return {"added": True, "message": "Done. Open a new terminal and type: flowforge status"}


def _flowforges_link(link: Path) -> bool:
    """A link this button made: it points at a FlowForge app's program (…/FlowForge.app/Contents/MacOS/flowforge)."""
    if not link.is_symlink():
        return False
    target = Path(os.readlink(link))
    return target.name == "flowforge" and any(p.endswith(".app") and "flowforge" in p.lower() for p in target.parts)


def _add_macos(exe: Path, home: Path) -> dict[str, Any]:
    cmd = home / CMD_DIR
    cmd.mkdir(parents=True, exist_ok=True)
    link = cmd / "flowforge"
    if link.is_symlink() or link.exists():
        if not _flowforges_link(link):   # yours: never deleted (Codex review)
            return {"added": False, "message": f"{link} already exists and isn't FlowForge's: left as it is. "
                                               "Move it, then try again."}
        link.unlink()
    link.symlink_to(exe)
    for name in PROFILES:
        profile = home / name
        text = profile.read_text() if profile.is_file() else ""
        if PROFILE_LINE not in text:
            profile.write_text(text + ("" if not text or text.endswith("\n") else "\n") + PROFILE_LINE + "\n")
    return {"added": True, "message": "Done. Open a new terminal and type: flowforge status"}
