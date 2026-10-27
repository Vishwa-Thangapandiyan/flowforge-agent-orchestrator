"""Security findings from what the scan read (D31): keys in code and configs, plain http, unpinned or over-broad MCP
servers. Each with the dependency it belongs to, a masked excerpt, a one-sentence fix and a prompt for a coding agent.

Called by the scanner with the text it already has; nothing is read again, run or sent (D20).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from flowforge.scan.models import Dependency, Finding
from flowforge.scan.urls import is_local
from flowforge.security.finders import KeyHit, find_keys
from flowforge.security.logfilter import KEY_PATTERNS

Excerpt = Callable[[str, int], tuple[int, list[str]]]   # (path, line) -> (first line, masked lines)
CODE = frozenset({"python", "javascript", "typescript", "dart"})
NEAR = 3   # a key belongs to the dependency called within this many lines of where its name is used
RUNNERS = frozenset({"npx", "uvx", "bunx", "pnpx"})
BROAD = re.compile(r"^(?:/|~/?|\$\{?HOME\}?/?|[A-Za-z]:[\\/]?)$")
_HTTP = re.compile(r"""\bhttp://([^/\s'"`:?#]+)""")
LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class ConfigKey:
    """A key-like env name whose value is written in an MCP config (the value itself is never passed here)."""

    dep_id: str
    server: str
    name: str
    path: str
    line: int


def _id(kind: str, path: str, line: int) -> str:
    return f"{kind}-{re.sub(r'[^a-z0-9]+', '-', path.lower()).strip('-')}-{line}"[:120]


def env_name(name: str | None, label: str) -> str:
    """`apiKey` → API_KEY, `GOOGLE_STATIC_MAPS_KEY` stays; no name → one from the kind of key."""
    base = name or label
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base)
    return re.sub(r"[^A-Za-z0-9]+", "_", snake).strip("_").upper() or "API_KEY"


def _lookup(language: str | None, name: str) -> str:
    return {"python": f'os.environ["{name}"]', "javascript": f"process.env.{name}", "typescript": f"process.env.{name}",
            "dart": f"String.fromEnvironment('{name}') (or your env package)"}.get(language or "", "the environment")


class _Builder:
    def __init__(self, texts: dict[str, list[str]], deps: list[Dependency],
                 places: dict[str, list[tuple[str, int, str]]], excerpt: Excerpt):
        self.texts, self.deps, self.places, self.excerpt = texts, deps, places, excerpt
        self.out: list[Finding] = []

    def add(self, kind: str, level: str, path: str, line: int, title: str, fix: str, prompt: str,
            dep_id: str | None) -> None:
        first, lines = self.excerpt(path, line)
        self.out.append(Finding(id=_id(kind, path, line), kind=kind, level=level, title=title[:160],
                                ref=f"{path}:{line}", line=line, dep_id=dep_id, first_line=first, excerpt=lines,
                                fix=fix, prompt=prompt))

    def dep_at(self, path: str, line: int, near: int = 0) -> str | None:
        for dep in self.deps:
            if any(p == path and abs(n - line) <= near for p, n, _ in self.places.get(dep.id, [])):
                return dep.id
        return None

    def key_owner(self, path: str, hit: KeyHit) -> str | None:
        """The dependency on the key's own line; else the one called near a line that uses the key's name."""
        if dep := self.dep_at(path, hit.line):
            return dep
        if not hit.name:
            return None
        used = re.compile(rf"(?<![\w$]){re.escape(hit.name)}(?![\w$])")
        for p, lines in sorted(self.texts.items()):
            for n, text in enumerate(lines, 1):
                if (p, n) != (path, hit.line) and used.search(text) and (dep := self.dep_at(p, n, NEAR)):
                    return dep
        return None

    def keys(self, path: str, language: str | None, skip: set[int], test: bool = False) -> None:
        for hit in find_keys("\n".join(self.texts[path]), language if language in CODE else None):
            if hit.line in skip or (test and _made_up(self.texts[path][hit.line - 1])):
                continue
            dep_id = self.key_owner(path, hit)
            used = next((f" for {d.name}" for d in self.deps if d.id == dep_id), "")
            article = "An" if hit.label[0].lower() in "aeiou" else "A"
            name = env_name(hit.name, "API_KEY" if hit.label == "secret" else hit.label)
            where = "a test file" if test else "the code"   # a test's key: still a key, but less exposed (D52)
            self.add("key_in_code", "medium" if test else "high", path, hit.line,
                     f"{article} {hit.label} is written in {where}",
                     "Move it to .env and read it from the environment. Then replace the key: it may be in your git "
                     "history.",
                     f"In {path}:{hit.line}, a {hit.label}{used} is written in the code. Move it to an environment "
                     f"variable named {name}: add it to .env (check that .env is in .gitignore) and read it with "
                     f"{_lookup(language, name)} wherever it is used. Remove the written value. Never print or log it. "
                     "Then remind me to replace the key with the provider, because the old one may be in git history.",
                     dep_id)

    def config_key(self, c: ConfigKey) -> None:
        self.add("key_in_config", "high", c.path, c.line, f"{c.server}'s config holds {c.name} as plain text",
                 f'Reference it instead ("${{{c.name}}}") and keep the value in your environment. '
                 "Then replace the key.",
                 f'In {c.path}:{c.line}, the MCP server "{c.server}" gets {c.name} as a value written in the file. '
                 f'Change it to "${{{c.name}}}" so the value comes from the environment, and tell me to set {c.name} '
                 "there and to replace the old key, because it may be in git history. Never print the value.",
                 c.dep_id)

    def plain_http(self, dep: Dependency) -> None:
        for path, line, _ in self.places.get(dep.id, []):
            text = self.texts.get(path, [""] * line)[line - 1] if line <= len(self.texts.get(path, [])) else ""
            host = next((h for h in _HTTP.findall(text) if not is_local(h)), None)
            if host:
                self.add("plain_http", "medium", path, line, f"{dep.name} is called over http://",
                         "Use https:// if the service offers it: anyone on the network can read or change plain http.",
                         f"In {path}:{line}, {dep.name} is called over plain http://{host}. Check that {host} serves "
                         "https, and if it does, change the address to https://. If it doesn't, tell me, and don't "
                         "send keys or personal data to it.", dep.id)
                return

    def server(self, dep: Dependency) -> None:
        if not dep.command or not dep.evidence:
            return
        path, _, line = dep.evidence[0].ref.rpartition(":")
        program, args = PurePosixPath(dep.command[0]).name, dep.command[1:]
        if program in RUNNERS:
            package = args[args.index("--from") + 1] if "--from" in args[:-1] else next(
                (a for a in args if not a.startswith("-")), None)
            if package and not _pinned(program, package):
                pin = f"{package}=={{version}}" if program == "uvx" else f"{package}@{{version}}"
                self.add("unpinned_server", "medium", path, int(line), f"{dep.name} runs whatever version is newest",
                         f"Pin a version ({pin.format(version='<version>')}) so a new release can't change it "
                         "under you.",
                         f'In {dep.evidence[0].ref}, the MCP server "{dep.name}" starts {package} with no version, so '
                         f"each start may run a new release. Find the version in use now and pin it: "
                         f"{pin.format(version='<that version>')}. Change nothing else.", dep.id)
        if any("server-filesystem" in a for a in args) and (wide := next((a for a in args if BROAD.match(a)), None)):
            self.add("broad_files", "medium", path, int(line), f"{dep.name} can read every file under {wide}",
                     "Give it only the folder it needs.",
                     f'In {dep.evidence[0].ref}, the filesystem MCP server "{dep.name}" is given {wide}, so it can '
                     "read and change everything under it. Replace it with the one folder the app needs. Ask me which "
                     "folder if it isn't clear.", dep.id)


def _pinned(program: str, package: str) -> bool:
    if program == "uvx":
        return "==" in package or "@" in package
    return package.count("@") >= 2 if package.startswith("@") else "@" in package


# In a test or fake-data file, a key whose value says it's made up isn't reported (D52). The value decides, not the
# line: `mock_client = Client(api_key="sk-…")` still counts.
_MADE_UP = re.compile(r"fake|dummy|mock|stub|placeholder|x{4,}|0{6,}|12345678", re.IGNORECASE)
_QUOTED = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""")


def _made_up(line: str) -> bool:
    values = [m.group(0) for p in KEY_PATTERNS for m in p.finditer(line)]
    values = values or [m.group(2) for m in _QUOTED.finditer(line)]   # a key of no known shape: the strings
    return bool(values) and all(_MADE_UP.search(v) for v in values)


def findings_for(texts: dict[str, list[str]], languages: dict[str, str | None], deps: list[Dependency],
                 places: dict[str, list[tuple[str, int, str]]], config_keys: list[ConfigKey],
                 excerpt: Excerpt, tests: set[str] | None = None) -> list[Finding]:
    """Every finding, high first, then by file and line."""
    b = _Builder(texts, deps, places, excerpt)
    for c in config_keys:
        b.config_key(c)
    in_configs = {(c.path, c.line) for c in config_keys}
    for path in sorted(texts):
        b.keys(path, languages.get(path), {n for p, n in in_configs if p == path}, path in (tests or set()))
    for dep in deps:
        if dep.kind in ("api", "llm"):
            b.plain_http(dep)
        elif dep.kind == "mcp":
            b.server(dep)
    return sorted(b.out, key=lambda f: (LEVEL_ORDER[f.level], f.ref.rsplit(":", 1)[0], f.line))
