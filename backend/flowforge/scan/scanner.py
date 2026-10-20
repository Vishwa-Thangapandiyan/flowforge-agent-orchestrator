"""`scan(root)`: a repo's dependencies with evidence, from plain code (D20, D21).

Read-only: nothing in the repo is imported, run or installed, and nothing is sent anywhere. Per-language
readers produce `FileFacts`; this module merges them into one `Dependency` per stable id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from flowforge.scan import manifests, mcp_config, patterns, python_ast, services
from flowforge.scan.facts import FileFacts, Ref
from flowforge.scan.files import language, list_files
from flowforge.scan.models import Dependency, EnvName, ScanEvidence, ScanResult
from flowforge.scan.urls import api_shaped, clean_url, host_of, is_ignored, is_local
from flowforge.security.logfilter import Redactor

EXCERPT_RADIUS = 2
MAX_LINE = 160
MAX_EVIDENCE = 10   # per dependency; `places` counts them all
_redactor = Redactor()

Constants = dict[str, tuple[str, str, int]]   # NAME -> (value, path, line), from every Python file


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:56]


@dataclass
class _Dep:
    kind: str
    name: str
    catalog: str | None = None
    target: str | None = None
    targets: list[str] = field(default_factory=list)
    model: str | None = None
    command: list[str] | None = None
    scope: str = "app"
    via: str | None = None
    env_names: list[str] = field(default_factory=list)
    confirmed: bool = False
    places: list[tuple[str, int, str]] = field(default_factory=list)   # (path, line, what it shows)

    def add(self, path: str, line: int, text: str) -> None:
        if not any(p == path and n == line for p, n, _ in self.places):
            self.places.append((path, line, text))


class _Merge:
    def __init__(self, texts: dict[str, list[str]], constants: Constants):
        self.texts = texts
        self.constants = constants
        self.deps: dict[str, _Dep] = {}

    def resolve(self, ref: Ref) -> tuple[str | None, tuple[str, int] | None]:
        """A literal's value, or a constant's value and where it is defined."""
        if ref.literal is not None:
            return ref.literal, None
        if ref.name in self.constants:
            value, path, line = self.constants[ref.name]
            return value, (path, line)
        return None, None

    def api(self, url: str, path: str, line: int, confirmed: bool, text: str, via: str | None = None) -> None:
        host = host_of(url)
        if is_local(host) or is_ignored(host):
            return
        service = services.by_host(host)
        if service is not None and service["kind"] == "llm":
            return   # an LLM's address belongs to the LLM rule
        if service is not None:   # a known service: all its hosts are one dependency
            dep = self.deps.setdefault(f"api-{_slug(service['id'])}",
                                       _Dep(kind="api", name=service["name"], catalog=service["id"]))
        else:
            dep = self.deps.setdefault(f"api-{_slug(host)}", _Dep(kind="api", name=host))
        if url not in dep.targets:
            dep.targets.append(url)
        dep.target = dep.target or url
        # a www. page the app opens (a link, an attribution) is not a call, even through Uri.parse (D21)
        page = host.startswith("www.") and service is None and not api_shaped(url)
        dep.confirmed = dep.confirmed or (confirmed and not page) or service is not None or api_shaped(url)
        dep.via = dep.via or via
        dep.add(path, line, text)

    def service_sdks(self, f: FileFacts) -> None:
        """An imported SDK of a hosted service (stripe, supabase…) is that service, URL or not (D21)."""
        for pkg, line in f.imports:
            service = services.by_sdk(pkg)
            if service is None or service["kind"] != "api":
                continue
            dep = self.deps.setdefault(f"api-{_slug(service['id'])}",
                                       _Dep(kind="api", name=service["name"], catalog=service["id"]))
            dep.confirmed = True
            dep.add(f.path, line, f"imports {pkg.split('.')[0]}")

    def installed(self, packages: list[tuple[str, str, int]], facts: list[FileFacts]) -> None:
        """An installed service SDK no code imports: an unconfirmed hint (D21). Imported ones are covered."""
        used = {s["id"] for f in facts for pkg, _ in f.imports if (s := services.by_sdk(pkg))}
        for pkg, path, line in packages:
            service = services.by_sdk(pkg)
            if service is None or service["id"] in used:
                continue
            dep = self.deps.setdefault(f"{service['kind']}-{_slug(service['id'])}",
                                       _Dep(kind=service["kind"], name=service["name"], catalog=service["id"]))
            dep.add(path, line, f"lists {pkg}")

    def local(self, command: list[str], path: str, line: int) -> None:
        name = command[-1]
        stem = name.rsplit("/", 1)[-1].rsplit(".", 1)[0] if len(command) > 1 else name.rsplit("/", 1)[-1]
        dep = self.deps.setdefault(f"local-{_slug(stem)}", _Dep(kind="local", name=name))
        dep.command = dep.command or command
        dep.target = dep.target or " ".join(command)
        dep.confirmed = True
        dep.add(path, line, "runs it")

    def mcp(self, server: mcp_config.Server, path: str, scope: str) -> None:
        dep = self.deps.setdefault(f"mcp-{_slug(server.name)}", _Dep(kind="mcp", name=server.name))
        dep.command = dep.command or server.command
        dep.target = dep.target or " ".join(server.command) or None
        dep.scope = "app" if "app" in (dep.scope, scope) and dep.places else scope
        dep.env_names = sorted({*dep.env_names, *server.env_names})
        dep.confirmed = True
        dep.add(path, server.line, "configured here")

    def llms(self, f: FileFacts) -> None:
        """One LLM per provider: the client's base URL decides it, else the SDK's own service."""
        sdks = [(pkg, line, s) for pkg, line in f.imports if (s := services.by_sdk(pkg)) and s["kind"] == "llm"]
        if not sdks:
            return
        found: list[_Dep] = []
        clients = [c for c in f.clients if (s := services.by_sdk(c.sdk)) and s["kind"] == "llm"]
        for client in clients:
            base, defined = self.resolve(client.base_url)
            url = clean_url(base) if base else None
            service = services.by_host(host_of(url)) if url else None
            if url and service is None:   # a provider we don't know: named by its address
                dep = self.deps.setdefault(f"llm-{_slug(host_of(url))}", _Dep(kind="llm", name=host_of(url)))
            else:
                service = service or services.by_sdk(client.sdk)
                dep = self.deps.setdefault(f"llm-{_slug(service['id'])}",
                                           _Dep(kind="llm", name=service["name"], catalog=service["id"]))
            dep.target = dep.target or (host_of(url) if url else None)
            dep.add(f.path, client.line, "creates the client")
            if defined:
                dep.add(*defined, "its address")
            found.append(dep)
        if not found:   # imported, no client seen: the SDK's own provider
            pkg, line, service = sdks[0]
            found.append(self.deps.setdefault(f"llm-{_slug(service['id'])}",
                                              _Dep(kind="llm", name=service["name"], catalog=service["id"])))
        for dep in found:
            dep.confirmed = True
            for pkg, line, _ in sdks:
                dep.add(f.path, line, f"imports {pkg.split('.')[0]}")
            for ref, line in f.models:
                value, defined = self.resolve(ref)
                if value:
                    dep.model = dep.model or value
                    dep.add(*(defined or (f.path, line)), "the model")

    def evidence(self, path: str, line: int, text: str) -> ScanEvidence:
        lines = self.texts.get(path, [])
        first = max(1, line - EXCERPT_RADIUS)
        last = min(len(lines), line + EXCERPT_RADIUS)
        excerpt = [_redactor.redact_text(raw)[:MAX_LINE] for raw in lines[first - 1:last]]
        return ScanEvidence(ref=f"{path}:{line}", text=text, first_line=first, lines=excerpt, highlight=line)

    def result(self, env: dict[tuple[str, int], list[str]]) -> list[Dependency]:
        out = []
        for dep_id, d in self.deps.items():
            places = sorted(d.places, key=lambda p: (p[0], p[1]))
            names = list(dict.fromkeys([*d.env_names, *(n for p, line, _ in places for n in env.get((p, line), []))]))
            out.append(Dependency(
                id=dep_id, kind=d.kind, name=d.name, catalog=d.catalog, target=d.target, targets=d.targets,
                model=d.model, command=d.command, scope=d.scope, via=d.via,
                status="confirmed" if d.confirmed else "unconfirmed",
                evidence=[self.evidence(p, n, t) for p, n, t in places[:MAX_EVIDENCE]], places=len(places),
                env_names=names))
        return sorted(out, key=lambda d: (d.kind, d.name.lower()))


def _mcp_scopes(rel: str, servers: list[mcp_config.Server], facts: list[FileFacts]) -> dict[str, str]:
    """D21: a config's servers are the app's when its code names the config file; otherwise a server is the
    app's only when code that imports `mcp` passes its name to a call. The rest serve your coding tools."""
    config_name = rel.rsplit("/", 1)[-1]
    if any(config_name in f.strings or rel in f.strings for f in facts):
        return {s.name: "app" for s in servers}
    mcp_code = [f for f in facts if any(pkg == "mcp" or pkg.startswith("mcp.") for pkg, _ in f.imports)]
    return {s.name: "app" if any(s.name in f.call_strings for f in mcp_code) else "dev_tool" for s in servers}


def scan(root: str | Path) -> ScanResult:
    root = Path(root).resolve()
    listing = list_files(root)
    texts: dict[str, list[str]] = {}
    facts: list[FileFacts] = []
    configs: list[tuple[str, list[mcp_config.Server]]] = []
    installed: list[tuple[str, str, int]] = []   # (package, file, line) from dependency files
    languages: dict[str, int] = {}
    for rel in listing.files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        lang = language(rel)
        if mcp_config.is_config(rel):
            configs.append((rel, mcp_config.parse(text)))
        elif manifests.is_manifest(rel):
            installed += [(pkg, rel, line) for pkg, line in manifests.parse(rel, text)]
        elif lang == "python":
            try:
                facts.append(python_ast.extract(rel, text))
            except SyntaxError:
                listing.skip("unparsable")
                continue
        elif lang is not None:
            facts.append(patterns.extract(rel, text, lang))
        texts[rel] = text.splitlines()
        if lang:
            languages[lang] = languages.get(lang, 0) + 1

    constants: Constants = {name: (value, f.path, line) for f in facts for name, (value, line) in f.constants.items()}
    merge = _Merge(texts, constants)
    app_servers: set[str] = set()
    for rel, servers in configs:
        scope_of = _mcp_scopes(rel, servers, facts)
        for server in servers:
            merge.mcp(server, rel, scope_of[server.name])
            if scope_of[server.name] == "app":
                app_servers.add(server.name)
    for f in facts:
        merge.llms(f)
        merge.service_sdks(f)
        for command, line in f.commands:
            merge.local(command, f.path, line)
        for hit in f.urls:
            via = next((f"mcp-{_slug(s)}" for s in hit.call_strings if s in app_servers), None)
            if hit.url:
                merge.api(hit.url, f.path, hit.line, hit.confirmed, "the address", via)
            elif hit.name in constants:
                value, where, at = constants[hit.name]
                url = clean_url(value)
                if url:
                    merge.api(url, where, at, hit.confirmed, "the address", via)
                    merge.api(url, f.path, hit.line, hit.confirmed, "calls it", via)

    merge.installed(installed, facts)

    env: dict[tuple[str, int], list[str]] = {}
    seen: dict[str, str] = {}
    for f in facts:
        for name, line in f.env:
            env.setdefault((f.path, line), []).append(name)
            seen.setdefault(name, f"{f.path}:{line}")
    return ScanResult(root=root.name, files_scanned=len(listing.files), skipped=listing.skipped,
                      languages=languages, dependencies=merge.result(env),
                      env_names=[EnvName(name=n, ref=r) for n, r in sorted(seen.items())])
