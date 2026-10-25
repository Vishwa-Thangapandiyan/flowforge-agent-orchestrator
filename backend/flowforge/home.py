"""Where FlowForge's files are (D34): per-user state in FLOWFORGE_HOME (databases, artifacts, connectors.json), and
the files it ships (the dashboard, the example app, sample workflows) inside the installed package, or in the
checkout when run from source."""

from __future__ import annotations

import os
import sys
from importlib import metadata
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
CHECKOUT = PACKAGE.parents[1]
DIST_NAME = "flowforge-map"   # the name on PyPI (D34); the command and the import stay `flowforge`
IN_CHECKOUT = (CHECKOUT / "pyproject.toml").is_file() and (CHECKOUT / "backend" / "flowforge").is_dir()

# name -> (inside the package, in the checkout)
_FILES = {
    "dashboard": ("_dashboard", "frontend/dist"),
    "example": ("_example/trip-planner", "examples/trip-planner"),
    "workflows": ("_workflows", "backend/workflows"),
    "classic": ("_classic.html", "frontend/classic.html"),
}


def resource(name: str, package: Path = PACKAGE, checkout: Path = CHECKOUT) -> Path:
    """A shipped file or folder: the packaged copy when installed, else the checkout's."""
    packaged, source = _FILES[name]
    inside = package / packaged
    return inside if inside.exists() else checkout / source


def version() -> str:
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        return "0.0.0"


def install_kind() -> str:
    """"checkout" (run from source), "desktop" (the desktop app's bundled Python, D42), "npx" (the same program, run
    by `npx flowforge-map`, D49), "uvx" (a throwaway environment uv made for one run) or "pip" (installed)."""
    if IN_CHECKOUT:
        return "checkout"
    if getattr(sys, "frozen", False):   # the frozen program: the desktop app's, or one `npx flowforge-map` runs (D49)
        return "npx" if os.getenv("FLOWFORGE_LAUNCHER") == "npx" else "desktop"
    return "uvx" if "archive-v" in Path(sys.prefix).as_posix() else "pip"


def _cargo_build(path: Path) -> bool:
    """A binary inside a Rust `target/debug` or `target/release` folder: a desktop development build."""
    parts = [p.lower() for p in path.parts]
    return any(a == "target" and b in ("debug", "release") for a, b in zip(parts, parts[1:], strict=False))


def command_line(*args: str) -> str:
    """A `flowforge …` command for a person to type, matching how FlowForge was installed (D34, D36)."""
    import shlex

    kind = install_kind()
    if kind == "checkout":
        prefix = ["uv", "--directory", str(CHECKOUT), "run", "flowforge"]
    elif kind == "uvx":
        prefix = ["uvx", DIST_NAME]
    elif kind == "npx":
        prefix = ["npx", DIST_NAME]
    elif kind == "desktop" and not _cargo_build(Path(sys.executable)):   # the installed app's binary (D42)
        prefix = [sys.executable]
    elif kind == "desktop":   # a development build moves with every rebuild: the command that stays
        import shutil

        prefix = ["flowforge"] if shutil.which("flowforge") else ["uvx", DIST_NAME]
    else:
        prefix = ["flowforge"]
    return shlex.join([*prefix, *args])


def flowforge_home() -> Path:
    return Path(os.getenv("FLOWFORGE_HOME") or Path.home() / ".flowforge")


def database_path(example: bool = False) -> Path:
    """The SQLite file: FLOWFORGE_DB, else example.db in FLOWFORGE_HOME for example data, else flowforge.db next to
    the checkout, or in FLOWFORGE_HOME when installed. The dashboard and the MCP server open the same one (D29)."""
    if example:
        default = flowforge_home() / "example.db"
    else:
        default = CHECKOUT / "flowforge.db" if IN_CHECKOUT else flowforge_home() / "flowforge.db"
    return Path(os.getenv("FLOWFORGE_DB") or default)
