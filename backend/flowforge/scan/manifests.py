"""Installed packages from dependency files (D21): requirements*.txt, pyproject.toml, package.json, pubspec.yaml.

Only package names and their line are kept. An installed service SDK the code never imports becomes an
unconfirmed hint on the map.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import PurePosixPath

_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._\-]*)")
_PUBSPEC_DEP = re.compile(r"^  ([A-Za-z0-9_]+)\s*:")


def is_manifest(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return name in ("pyproject.toml", "package.json", "pubspec.yaml") or \
        (name.startswith("requirements") and name.endswith(".txt"))


def _line_of(lines: list[str], package: str) -> int:
    pattern = re.compile(rf"""(^|[\s"'\[]){re.escape(package)}([\s"'=<>~!:\[;,]|$)""")
    return next((i for i, raw in enumerate(lines, 1) if pattern.search(raw)), 1)


def parse(rel: str, text: str) -> list[tuple[str, int]]:
    """(package, line) for every dependency the file lists."""
    name = PurePosixPath(rel).name
    lines = text.splitlines()
    if name.endswith(".txt"):
        out = []
        for i, raw in enumerate(lines, 1):
            raw = raw.split("#")[0]
            if raw.strip().startswith("-"):
                continue
            if m := _REQUIREMENT.match(raw):
                out.append((m.group(1), i))
        return out
    if name == "pubspec.yaml":
        out, inside = [], False
        for i, raw in enumerate(lines, 1):
            if raw and not raw[0].isspace():
                inside = raw.rstrip().rstrip(":") in ("dependencies", "dev_dependencies")
            elif inside and (m := _PUBSPEC_DEP.match(raw)) and m.group(1) != "flutter":
                out.append((m.group(1), i))
        return out
    try:
        data = json.loads(text) if name == "package.json" else tomllib.loads(text)
    except ValueError:
        return []
    names: list[str] = []
    if name == "package.json":
        for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            names += list(data.get(key, {}) or {})
    else:
        project = data.get("project", {})
        specs = list(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            specs += group
        names += [m.group(1) for spec in specs if (m := _REQUIREMENT.match(spec))]
        names += [n for n in data.get("tool", {}).get("poetry", {}).get("dependencies", {}) if n != "python"]
    return [(n, _line_of(lines, n)) for n in dict.fromkeys(names)]
