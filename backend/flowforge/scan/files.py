"""Which files the scan reads (D21): code and known config files, never anything vendored, built or ignored."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from flowforge.scan.manifests import is_manifest
from flowforge.scan.mcp_config import is_config

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "build", "dist", ".dart_tool", "__pycache__", "vendor",
                       "tests", "test", "__tests__"})
MAX_BYTES = 1_000_000
LANGUAGES = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
             ".ts": "typescript", ".tsx": "typescript", ".dart": "dart"}


@dataclass
class Listing:
    files: list[str] = field(default_factory=list)          # paths relative to the root, "/"-separated
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def language(rel: str) -> str | None:
    return LANGUAGES.get(Path(rel).suffix.lower())


def wanted(rel: str) -> bool:
    """Code files and MCP config files. Hidden folders (.claude, .cursor, .github …) hold your tools, not
    your app (D21): only their MCP config files are read."""
    if any(part.startswith(".") for part in Path(rel).parent.parts):
        return is_config(rel)
    return language(rel) is not None or is_config(rel) or is_manifest(rel)


def _git_files(root: Path) -> list[str] | None:
    """Files git tracks or doesn't ignore, relative to `root`; None when `root` isn't in a git repo.
    A local command only: `ls-files` never touches the network."""
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                              capture_output=True, timeout=20, check=False,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return sorted({p for p in done.stdout.decode("utf-8", "replace").split("\0") if p})


def _walk(root: Path) -> list[str]:
    found = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        found += [(Path(folder) / name).relative_to(root).as_posix() for name in sorted(names)]
    return found


def list_files(root: Path) -> Listing:
    out = Listing()
    root = root.resolve()
    candidates = _git_files(root)
    if candidates is None:
        candidates = _walk(root)
    for rel in candidates:
        if any(part in SKIP_DIRS for part in Path(rel).parent.parts) or not wanted(rel):
            continue
        path = root / rel
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            out.skip("outside")
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_BYTES:
            out.skip("too_big")
            continue
        out.files.append(rel)
    return out
