"""`scan(root)`: a repo's dependencies with evidence, from plain code (D20, D21, D22).

Read-only: nothing in the repo is imported, run or installed, and nothing is sent anywhere. Per-language
readers produce `FileFacts`; this module merges them into one `Dependency` per stable id.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from flowforge.scan import manifests, mcp_config, patterns, python_ast, services
from flowforge.scan.facts import FileFacts, Ref
from flowforge.scan.files import language, list_files
from flowforge.scan.models import Dependency, EnvName, ScanEvidence, ScanResult
from flowforge.scan.urls import api_shaped, clean_url, host_of, is_local, is_not_a_service
from flowforge.security.findings import ConfigKey, findings_for
from flowforge.security.logfilter import Redactor, redact_code

EXCERPT_RADIUS = 2
MAX_LINE = 160
MAX_EVIDENCE = 10   # per dependency; `places` counts them all
_redactor = Redactor()

Constants = dict[str, tuple[str, str, int]]   # NAME -> (value, path, line), from every Python file


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:56]


def _shared_target(urls: list[str]) -> str:
    """The address to check (D23): on the host most of the URLs use, the one URL or the longest path they share,
    up to a `/`."""
    hosts = [urlsplit(u).netloc for u in urls]
    host = max(hosts, key=hosts.count)   # the first one on a tie
    same_host = [u for u, h in zip(urls, hosts, strict=True) if h == host]
    if len(same_host) == 1:
        return same_host[0]
    first = urlsplit(same_host[0])
    root = f"{first.scheme}://{host}/"
    shared = os.path.commonprefix(same_host)
    shared = shared[:shared.rfind("/") + 1]
    return shared if len(shared) > len(root) else root


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
    vias: set[str] = field(default_factory=set)   # MCP servers this host was reached through
    direct: bool = False                           # …and whether the code also reaches it itself
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

    def service_dep(self, service: dict) -> _Dep:
        """The one dependency of a known service (D22: all its hosts and SDKs merge into it)."""
        return self.deps.setdefault(f"{service['kind']}-{_slug(service['id'])}",
                                    _Dep(kind=service["kind"], name=service["name"], catalog=service["id"]))

    def api(self, url: str, path: str, line: int, confirmed: bool, text: str, via: str | None = None) -> None:
        host = host_of(url)
        if is_local(host) or is_not_a_service(host):
            return
        service = services.by_host(host)
        if service is not None and service["kind"] == "llm":
            return   # an LLM's address belongs to the LLM rule
        if service is not None:
            dep = self.service_dep(service)
        else:
            dep = self.deps.setdefault(f"api-{_slug(host)}", _Dep(kind="api", name=host))
        if url not in dep.targets:
            dep.targets.append(url)
        dep.target = _shared_target(dep.targets)
        # a www. page the app opens (a link, an attribution) is not a call, even through Uri.parse (D21)
        page = host.startswith("www.") and service is None and not api_shaped(url)
        dep.confirmed = dep.confirmed or (confirmed and not page) or service is not None or api_shaped(url)
        if via:
            dep.vias.add(via)
        else:
            dep.direct = True
        dep.add(path, line, text)

    def service_sdks(self, f: FileFacts) -> None:
        """An imported SDK of a hosted service (stripe, supabase…) is that service, URL or not (D21)."""
        for pkg, line in f.imports:
            service = services.by_sdk(pkg)
            if service is None or service["kind"] != "api":
                continue
            dep = self.service_dep(service)
            dep.confirmed = True
            dep.add(f.path, line, f"imports {pkg.split('.')[0]}")

    def installed(self, packages: list[tuple[str, str, int]], facts: list[FileFacts]) -> None:
        """An installed service SDK no code imports: an unconfirmed hint (D21). Imported ones are covered."""
        used = {s["id"] for f in facts for pkg, _ in f.imports if (s := services.by_sdk(pkg))}
        for pkg, path, line in packages:
            service = services.by_sdk(pkg)
            if service is None or service["id"] in used:
                continue
            self.service_dep(service).add(path, line, f"lists {pkg}")

    def local(self, command: list[str], path: str, line: int) -> None:
        program = command[-1].rsplit("/", 1)[-1]
        stem = program.rsplit(".", 1)[0] if len(command) > 1 else program
        # a script is named for what it runs, "packing list"; a program keeps its own name (D23)
        name = re.sub(r"[_-]+", " ", stem) if len(command) > 1 else program
        dep = self.deps.setdefault(f"local-{_slug(stem)}", _Dep(kind="local", name=name))
        dep.command = dep.command or command
        dep.target = dep.target or " ".join(command)
        dep.confirmed = True
        dep.add(path, line, "runs it")

    def mcp(self, name: str, command: list[str], env_names: list[str], path: str, line: int, scope: str,
            text: str) -> None:
        dep = self.deps.get(f"mcp-{_slug(name)}")
        if dep is None:
            dep = self.deps[f"mcp-{_slug(name)}"] = _Dep(kind="mcp", name=name, scope=scope)
        elif scope == "app":
            dep.scope = "app"   # one place shows the app uses it: it is the app's
        dep.command = dep.command or command
        dep.target = dep.target or " ".join(command) or None
        dep.env_names = sorted({*dep.env_names, *env_names})
        dep.confirmed = True
        dep.add(path, line, text)

    def stdio(self, f: FileFacts) -> None:
        """An MCP server the code starts itself, named by its package: StdioServerParameters, StdioClientTransport."""
        for command, line in f.stdio:
            name = next((a for a in command[1:] if not a.startswith("-") and a != "."), command[0])
            self.mcp(name.split("@", 2)[1] if name.startswith("@") and name.count("@") > 1 else name, command, [],
                     f.path, line, "app", "starts it")

    def llms(self, f: FileFacts) -> None:
        """One LLM per provider: the client's base URL decides it, else the SDK's own service."""
        sdks = [(pkg, line, s) for pkg, line in f.imports if (s := services.by_sdk(pkg)) and s["kind"] == "llm"]
        if not sdks:
            self.routed_llms(f)
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
            found.append(self.service_dep(sdks[0][2]))
        for dep in found:
            dep.confirmed = True
            for pkg, line, _ in sdks:
                dep.add(f.path, line, f"imports {pkg.split('.')[0]}")
            for ref, line in f.models:
                value, defined = self.resolve(ref)
                if value:
                    dep.model = dep.model or value
                    dep.add(*(defined or (f.path, line)), "the model")

    def routed_llms(self, f: FileFacts) -> None:
        """An SDK that routes to many providers (litellm): each model name says which provider it is (D22)."""
        routers = [(pkg, line) for pkg, line in f.imports if services.is_router(pkg)]
        if not routers:
            return
        for ref, line in f.models:
            value, defined = self.resolve(ref)
            service = services.by_model(value) if value else None
            dep = self.service_dep(service) if service else self.deps.setdefault(
                "llm-litellm", _Dep(kind="llm", name="LiteLLM"))
            dep.model = dep.model or value
            dep.confirmed = True
            dep.add(*(defined or (f.path, line)), "the model")
            for pkg, at in routers:
                dep.add(f.path, at, f"imports {pkg.split('.')[0]}")

    def evidence(self, path: str, line: int, text: str) -> ScanEvidence:
        lines = self.texts.get(path, [])
        first = max(1, line - EXCERPT_RADIUS)
        last = min(len(lines), line + EXCERPT_RADIUS)
        excerpt = [redact_code(raw, _redactor)[:MAX_LINE] for raw in lines[first - 1:last]]
        return ScanEvidence(ref=f"{path}:{line}", text=text, first_line=first, lines=excerpt, highlight=line)

    def result(self, env: dict[tuple[str, int], list[str]]) -> list[Dependency]:
        out = []
        for dep_id, d in self.deps.items():
            places = sorted(d.places, key=lambda p: (p[0], p[1]))
            names = list(dict.fromkeys([*d.env_names, *(n for p, line, _ in places for n in env.get((p, line), []))]))
            out.append(Dependency(
                id=dep_id, kind=d.kind, name=d.name, catalog=d.catalog, target=d.target, targets=d.targets,
                model=d.model, command=d.command, scope=d.scope,
                via=next(iter(d.vias)) if len(d.vias) == 1 and not d.direct else None,   # only ever through it
                status="confirmed" if d.confirmed else "unconfirmed",
                evidence=[self.evidence(p, n, t) for p, n, t in places[:MAX_EVIDENCE]], places=len(places),
                env_names=names))
        return sorted(out, key=lambda d: (d.kind, d.name.lower()))


def _config_scope(rel: str, servers: list[mcp_config.Server], facts: list[FileFacts]) -> str:
    """D21: a config's servers are the app's when its code names the config file or a server in it; else they
    serve your coding tools. A server name only counts when code that imports `mcp` passes it to a call, so a
    common word such as "time" elsewhere doesn't make a config the app's (D22)."""
    config_name = rel.rsplit("/", 1)[-1]
    if any(config_name in f.strings or rel in f.strings for f in facts):
        return "app"
    mcp_code = [f for f in facts if any(pkg == "mcp" or pkg.startswith("mcp.") for pkg, _ in f.imports)]
    named = any(s.name in f.call_strings for s in servers for f in mcp_code)
    return "app" if named else "dev_tool"


@dataclass
class Places:
    """What the scan saw, for readers that follow calls (D25): every place behind each dependency, uncapped, as
    (path, line, what it shows); the MCP servers the app itself uses; and the facts of each Python file."""

    by_dep: dict[str, list[tuple[str, int, str]]]
    app_servers: set[str]
    facts: dict[str, FileFacts]
    code: dict[str, str] = field(default_factory=dict)   # every code file read -> its language (D32)


def scan(root: str | Path) -> ScanResult:
    """A repo's dependencies with evidence (D21): plain code, read-only, nothing sent (D20)."""
    return scan_with_places(root)[0]


def scan_with_places(root: str | Path) -> tuple[ScanResult, Places]:
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
            languages["json"] = languages.get("json", 0) + 1
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
        scope = _config_scope(rel, servers, facts)
        for server in servers:
            merge.mcp(server.name, server.command, server.env_names, rel, server.line, scope, "configured here")
        if scope == "app":
            app_servers |= {server.name for server in servers}
    for f in facts:
        merge.llms(f)
        merge.service_sdks(f)
        merge.stdio(f)
        for command, line in f.commands:
            merge.local(command, f.path, line)
        for hit in f.urls:
            via = next((f"mcp-{_slug(s)}" for s in hit.call_strings if s in app_servers), None)
            if hit.url:
                merge.api(hit.url, f.path, hit.line, hit.confirmed, "calls it" if hit.confirmed else "the address", via)
            elif hit.name in constants:
                value, where, at = constants[hit.name]
                url = clean_url(value)
                if url:
                    merge.api(url, where, at, hit.confirmed, "the address", via)
                    merge.api(url, f.path, hit.line, hit.confirmed, "calls it" if hit.confirmed else "uses the address",
                              via)

    merge.installed(installed, facts)

    env: dict[tuple[str, int], list[str]] = {}
    seen: dict[str, str] = {}
    for f in facts:
        for name, line in f.env:
            env.setdefault((f.path, line), []).append(name)
            seen.setdefault(name, f"{f.path}:{line}")
    dependencies = merge.result(env)
    by_dep = {dep_id: sorted(d.places) for dep_id, d in merge.deps.items()}
    config_keys = [ConfigKey(f"mcp-{_slug(server.name)}", server.name, name, rel, line)
                   for rel, servers in configs for server in servers for name, line in server.env_literals]

    def excerpt(path: str, line: int) -> tuple[int, list[str]]:
        ev = merge.evidence(path, line, "")
        return ev.first_line or line, ev.lines

    findings = findings_for(texts, {rel: language(rel) for rel in texts}, dependencies, by_dep, config_keys, excerpt)
    result = ScanResult(root=root.name, files_scanned=len(listing.files), skipped=listing.skipped,
                        languages=languages, dependencies=dependencies,
                        env_names=[EnvName(name=n, ref=r) for n, r in sorted(seen.items())], findings=findings,
                        findings_checked=True)
    places = Places(by_dep=by_dep, app_servers=app_servers, facts={f.path: f for f in facts if f.language == "python"},
                    code={f.path: f.language for f in facts})
    return result, places
