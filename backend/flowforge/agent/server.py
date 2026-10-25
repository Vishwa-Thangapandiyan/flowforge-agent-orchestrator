"""FlowForge as an MCP server (D28, D29, D36): read-only tools a coding agent can ask about the repo it works in.

The map and the flow are read fresh from the repo on every call (plain code, nothing run, no LLM: D20). The
dashboard's database supplies what only it knows, when it maps the same repo: measured latencies, past checks,
the user's yes to starting MCP servers, and the saved map to compare with. Every answer is masked (D22).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from flowforge.api.apps import read_server_file
from flowforge.api.checks import CHECKABLE, check_workflow, command_text, confirmed_commands, target_for
from flowforge.api.issues import FIX_REQUESTS_SETTING, fix_requests
from flowforge.api.keys import add_key_request, clear_key_requests
from flowforge.api.scan import REPO_SETTING
from flowforge.checks import starts_process
from flowforge.connectors.registry import Registry
from flowforge.flow import flow_of
from flowforge.flowmap.models import CALL_KINDS, Flow
from flowforge.flowmap.validate import code_writes, critical
from flowforge.nodes.check_node import CheckNode
from flowforge.projects import Projects
from flowforge.scan import ScanResult, scan
from flowforge.scheduler.executor import StepState, run_workflow
from flowforge.security.keystore import NAME, KeyStore, report
from flowforge.security.logfilter import Redactor, redact_code, secret_values_for
from flowforge.security.masks import mask
from flowforge.storage import Storage, now_iso

log = logging.getLogger(__name__)

AGENT_CALLS_SETTING = "agent_calls"   # [{tool, repo, at, got}], newest first: the Connect page's list (D30)
KEEP_CALLS = 20
NOT_STARTED = "Not started: say yes in the dashboard first (Check now)"

INSTRUCTIONS = (
    "FlowForge maps the dependencies of the repo you are working in (LLMs, MCP servers, HTTP APIs, local programs), "
    "each with the file:line it comes from, checks their health, and shows the order the code calls them, the "
    "critical path and which calls could run together, and what is unsafe (keys in code, plain http, risky MCP "
    "servers). It reads code without running it and sends nothing to any "
    "LLM. Answers are masked: key values never appear. It doesn't edit code for you: you make the change, "
    "then call what_changed to confirm. When the user says \"do the FlowForge fixes\", call get_fix_requests."
)
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ASK = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
MAX_WAIT_S = 110
RUN = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)   # starts the user's app
CHECKS = ToolAnnotations(read_only_hint=True, open_world_hint=True)   # makes requests and may start servers


def _mask(value: Any, redactor: Redactor) -> Any:
    """Every string through the same masking as evidence: known key shapes, configured key values, URL credentials
    and queries, values given to key-like names."""
    if isinstance(value, str):
        return redact_code(value, redactor)
    if isinstance(value, dict):
        return {k: _mask(v, redactor) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, redactor) for v in value]
    return value


def _health(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {"status": "unchecked", "summary": "Not checked yet: call check_health"}
    return {k: row.get(k) for k in ("status", "summary", "reason", "fix", "latency_ms", "at") if row.get(k) is not None}


class _Repo:
    """One repo as the agent sees it, with the dashboard's data when the dashboard maps this same folder."""

    def __init__(self, root: Path, storage: Storage, transport: httpx.AsyncBaseTransport | None = None, *,
                 dashboards: bool = False):
        self.root, self.storage, self.transport = root.resolve(), storage, transport
        self.dashboards = dashboards   # the dashboard's own repo (the preview): its data applies even in example mode
        try:
            values = secret_values_for(Registry(storage).all())
        except Exception:   # a connector the registry can't read must not stop the server
            values = set()
        self.redactor = Redactor(values)

    @property
    def shared(self) -> bool:
        """Does the dashboard's database map this repo? Only then do its checks and yeses apply."""
        return self.dashboards or self.storage.setting(REPO_SETTING) == str(self.root)

    def answer(self, tool: str, data: dict[str, Any]) -> dict[str, Any]:
        """The masked answer, after noting the call for the Connect page (D30)."""
        note = {"tool": tool, "repo": self.root.name, "at": now_iso(), "got": headline(tool, data)}
        note = _mask(note, self.redactor)
        try:
            calls = json.loads(self.storage.setting(AGENT_CALLS_SETTING) or "[]")
        except ValueError:
            calls = []
        self.storage.set_setting(AGENT_CALLS_SETTING, json.dumps([note, *calls][:KEEP_CALLS]))
        return _mask({"repo": self.root.name, **data}, self.redactor)

    def latest(self) -> dict[str, dict[str, Any]]:
        if not self.shared:
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for row in self.storage.check_history(limit=1):
            rows.setdefault(row["dep_id"], row)
        return rows

    def flow(self) -> Any:
        return flow_of(self.root, self.storage.latest_latencies() if self.shared else {})

    def scan(self) -> ScanResult:
        return scan(self.root)


def _dependency(dep: Any, health: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": dep.id, "kind": dep.kind, "name": dep.name,
        "address": dep.target or (" ".join(dep.command) if dep.command else None), "model": dep.model,
        "places": [e.ref for e in dep.evidence], "places_total": dep.places,
        "confirmed": dep.status == "confirmed",
        "used_by": "your coding tools" if dep.scope == "dev_tool" else "the app",
        "via": dep.via, "health": _health(health),
    }


def _times(flow: Flow) -> dict[str, Any]:
    cp = critical(flow)
    names = {n.id: n for n in flow.nodes}
    return {
        "critical_path": [{"id": i, "name": names[i].what if names[i].kind in CALL_KINDS else names[i].title,
                           "ms": names[i].estimate_ms} for i in cp.path],
        "could_be_ms": round(cp.length_ms, 1), "as_written_ms": flow.written_ms,
    }


def _seconds(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{round(ms)} ms"


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


def headline(tool: str, data: dict[str, Any]) -> str | None:
    """A tool's answer in one line, from counts and times only (D30): the Connect page's cards and call list."""
    if tool == "get_map":
        return _plural(len(data["dependencies"]), "dependency", "dependencies")
    if tool == "check_health":
        counts = data["summary"]
        parts = [f"{counts[s]} {s}" for s in ("up", "warn", "down", "skipped") if counts.get(s)]
        return " · ".join(parts) or "Nothing to check"
    if tool in ("get_flow", "get_advice") and not data["available"]:
        return "No flow: no Python calls found"
    if tool == "get_flow":
        return f"{_seconds(data['as_written_ms'])} → {_seconds(data['could_be_ms'])}"
    if tool == "get_advice":
        n = len(data["advice"])
        if not n:
            return "Nothing to start together"
        return f"{_plural(n, 'way')} to be faster · saves ~{_seconds(data['saved_ms'])}"
    if tool == "get_security_findings":
        counts = data["summary"]
        return " · ".join(f"{counts[k]} {k}" for k in ("high", "medium", "low") if counts.get(k)) or "Nothing found"
    if tool == "get_keys":
        counts = data["summary"]
        parts = [f"{counts[k]} {w}" for k, w in (("missing", "missing"), ("env_file", "in .env")) if counts.get(k)]
        return " · ".join(parts) or ("All saved" if data["keys"] else "No keys read")
    if tool == "list_projects":
        return _plural(len(data["projects"]), "project")
    if tool == "request_key":
        return f"Asked for {data['name']}"
    if tool == "wait_for_keys":
        return "All saved" if data["done"] else f"{_plural(len(data['waiting']), 'key')} still missing"
    if tool == "get_fix_requests":
        return _plural(len(data["requests"]), "fix", "fixes") + " sent to you" if data["requests"] else "Nothing sent"
    if tool == "what_changed":
        if not data["saved"]:
            return "No saved map yet"
        return f"{len(data['added'])} added · {len(data['removed'])} removed"
    return None


def _map_data(r: _Repo) -> dict[str, Any]:
    result = r.scan()
    latest = r.latest()
    deps = [_dependency(d, latest.get(d.id)) for d in result.dependencies]
    counts = Counter(d.kind for d in result.dependencies)
    return {"dependencies": deps, "counts": dict(counts), "files_read": result.files_scanned}


def _security_data(result: ScanResult) -> dict[str, Any]:
    findings = [f.model_dump(mode="json") for f in result.findings]
    return {"findings": findings, "summary": dict(Counter(f["level"] for f in findings)),
            "note": "Catches known key formats and these patterns, not everything. Values are never shown."}


def _keys_data(root: Path, result: ScanResult) -> dict[str, Any]:
    """Names and statuses only: this server, which the agent starts, never reads a value (D36)."""
    from flowforge.security.wire import key_spots

    spots: dict[str, Any] = {}
    for sp in key_spots(root):   # where each key goes (D44): names and places, never a value
        spots.setdefault(sp.name, sp.public())
    found = report(KeyStore(root), result, verify=False, also=list(spots))
    for k in found:
        k["mask"] = mask(str(k["name"]))   # what you write where the value goes (D43)
        k["spot"] = spots.get(str(k["name"]))
    return {"keys": found, "summary": dict(Counter(k["status"] for k in found if k["status"] != "saved")),
            "how": HOW_KEYS,
            "note": "saved means FlowForge has it on record; this server never reads a value"}


HOW_KEYS = (
    "You never get a key's value and never need one. Where it works: (1) code reads the env var NAME; "
    "(2) a command-line argument such as --dart-define=NAME=ffkey://NAME; (3) a .env line NAME=ffkey://NAME "
    "(FlowForge sets the real NAME first and .env loaders keep it, unless told to override). Other config files "
    "(YAML, JSON, assets such as flutter_dotenv's) are NOT filled: read the env var there instead. Run the app with "
    "run_app; the output comes back masked. A missing key: request_key, then wait_for_keys.")
OPEN_FLOWFORGE = ("Open FlowForge first (the desktop app, or `flowforge` in a terminal): it starts the app with the "
                  "keys, so this server never holds one.")


def _fix_requests_data(r: _Repo) -> dict[str, Any]:
    """The user's queue (D37), without the issues the code no longer has. Only when the dashboard maps this repo."""
    if not r.shared:
        return {"requests": [], "message": "The dashboard doesn't map this repo, so nothing was sent from it."}
    queue = fix_requests(r.storage)
    here = str(r.root)
    now = {f.id for f in r.scan().findings}
    done = [q for q in queue if q["repo"] == here and q["id"] not in now]   # the code no longer has it
    if done:
        r.storage.set_setting(FIX_REQUESTS_SETTING, json.dumps([q for q in queue if q not in done]))
    live = [q for q in queue if q["repo"] == here and q["id"] in now]
    return {"requests": [{k: q.get(k) for k in ("id", "kind", "title", "ref", "fix", "prompt")} for q in live]}


def _flow_data(result: Any) -> dict[str, Any]:
    if result.flow is None:
        return {"available": False, "message": result.message}
    flow = result.flow
    calls = [{"id": n.id, "kind": n.kind, "service": n.title, "does": n.what, "ref": n.evidence[0].ref,
              "ms": n.estimate_ms, "measured": n.estimate_source == "measured", "writes": code_writes(n),
              "repeats": bool(n.repeats)} for n in flow.nodes if n.kind in CALL_KINDS]
    decisions = [{"id": n.id, "question": n.title, "condition": n.condition, "ref": n.evidence[0].ref}
                 for n in flow.nodes if n.kind == "decision"]
    lines = [{"from": e.source, "to": e.target, "when": e.when} for e in flow.edges]
    entries = [n.title for n in flow.nodes if n.kind == "start"]
    return {"available": True, "entry_points": entries, "calls": calls, "decisions": decisions, "lines": lines,
            **_times(flow)}


def _advice_data(result: Any) -> dict[str, Any]:
    if result.flow is None:
        return {"available": False, "message": result.message}
    advice = [a.model_dump(mode="json") for a in result.flow.advice]
    return {"available": True, "advice": advice, "saved_ms": round(sum(a["saved_ms"] for a in advice), 1)}


KIND_WORDS = {"llm": "LLM", "mcp": "MCP server", "api": "API", "local": "program"}


def preview(repo: Path, storage: Storage) -> dict[str, Any]:
    """What each tool would answer about the dashboard's repo now, as the Connect page's cards (D30). Health is the
    stored checks: nothing is run, and no call is noted."""
    r = _Repo(repo, storage, dashboards=True)
    deps = _map_data(r)
    counts = deps["counts"]
    kinds = " · ".join(_plural(counts[k], word) for k, word in KIND_WORDS.items() if counts.get(k))
    checked = [d["health"]["status"] for d in deps["dependencies"] if d["health"]["status"] != "unchecked"]
    health = {"summary": dict(Counter(checked))}
    tone = "bad" if "down" in checked else "warn" if "warn" in checked else "ok" if checked else "plain"
    read = r.flow()
    flow, advice = _flow_data(read), _advice_data(read)
    scanned = read.scan or r.scan()
    security, keys = _security_data(scanned), _keys_data(r.root, scanned)
    worst = next((lv for lv in ("high", "medium", "low") if security["summary"].get(lv)), None)
    cards = [
        {"tool": "get_map", "headline": headline("get_map", deps), "sub": kinds, "tone": "plain"},
        {"tool": "check_health", "headline": headline("check_health", health) if checked else "Not checked yet",
         "sub": f"{_plural(len(checked), 'last check')} stored" if checked else "Your agent can run the checks",
         "tone": tone},
        {"tool": "get_security_findings", "headline": headline("get_security_findings", security),
         "sub": "keys in code, plain http, risky MCP servers",
         "tone": {"high": "bad", "medium": "warn"}.get(worst or "", "ok")},
        {"tool": "get_keys", "headline": headline("get_keys", keys),
         "sub": "names only: the user types each key, hidden", "tone": "warn" if keys["summary"] else "ok"},
        {"tool": "get_flow", "headline": headline("get_flow", flow) if flow["available"] else None,
         "sub": "as written → could be" if flow["available"] else flow["message"], "tone": "plain"},
        {"tool": "get_advice", "headline": (_plural(len(advice["advice"]), "way") + " to be faster")
         if advice["available"] else None,
         "sub": f"saves ~{_seconds(advice['saved_ms'])}, the change written out" if advice["available"] else None,
         "tone": "warn" if advice["available"] and advice["advice"] else "plain"},
        {"tool": "get_fix_requests", "headline": headline("get_fix_requests", _fix_requests_data(r)),
         "sub": "issues you send from the Issues page", "tone": "plain"},
        {"tool": "what_changed", "headline": None, "sub": "After your agent edits: what it added or removed",
         "tone": "plain"},
    ]
    return _mask({"repo": r.root.name, "cards": cards}, r.redactor)


def build_server(repo: Path | None, storage: Storage | None, *,
                 transport: httpx.AsyncBaseTransport | None = None,
                 dashboard: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    """The server for one repo, or (repo None) for every project (D39: the agent is paired once). `transport` answers
    the health checks' requests in tests; `dashboard` reaches the running FlowForge in tests (D43)."""
    fixed = _Repo(repo, storage, transport) if repo is not None and storage is not None else None
    opened: dict[str, _Repo] = {}

    def pick(project: str | None) -> _Repo:
        """The repo a tool answers about: `project` (an id or a name) when given; else the one this server was started
        for; else the project whose folder holds where the agent works; else the one opened last."""
        registry = Projects()
        if project is None and fixed is not None:
            return fixed
        found = registry.find(project) if project else registry.for_folder(Path.cwd())
        if found is None and not project:
            found = max(registry.list(), key=lambda p: p.opened or p.added, default=None)
        if found is None:
            raise ToolError(f"no project {project!r}: call list_projects to see them" if project else
                             "no project yet: open FlowForge on your app's folder (`flowforge --repo PATH`)")
        if fixed is not None and Path(found.path) == fixed.root:
            return fixed
        if found.id not in opened:
            opened[found.id] = _Repo(Path(found.path), Storage(Path(found.db)), transport)
        return opened[found.id]

    async def ask_flowforge(r: _Repo, method: str, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        """The running FlowForge, which holds the keys, does the run (D43): found through server.json."""
        found = read_server_file()
        if not found or not found.get("port") or not found.get("token"):
            raise ToolError(OPEN_FLOWFORGE)
        project = Projects().by_folder(r.root)
        prefix = f"/p/{project.id}" if project else ""
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{int(found['port'])}", transport=dashboard,
                                         timeout=15) as client:
                answer = await client.request(method, prefix + path, json=body,
                                              headers={"X-FlowForge-Token": str(found["token"])})
        except httpx.HTTPError:
            raise ToolError(OPEN_FLOWFORGE) from None
        if answer.status_code == 403:
            raise ToolError("FlowForge refused: it was restarted. Call the tool again.")
        if answer.status_code == 404:
            raise ToolError("FlowForge doesn't know that run or request.")
        if answer.status_code == 409:
            raise ToolError(f"{answer.json().get('detail', 'Not ready.')} Ask the user for it with request_key, "
                            "then wait_for_keys.")
        return answer

    server = MCPServer(name="flowforge", title="FlowForge", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ)
    def list_projects() -> dict[str, Any]:
        """Every project FlowForge maps (D39): its id, name, folder and counts (dependencies, issues, keys missing).
        `current` marks the one your working directory is in, which every tool answers about by default; pass another
        one's id or name as `project` to ask about it."""
        from flowforge.api.projects import card

        here = Projects().for_folder(Path.cwd())
        rows = [{**card(p), "current": bool(here and p.id == here.id)} for p in Projects().list()]
        return _mask({"projects": rows}, Redactor())

    @server.tool(annotations=READ)
    def get_map(project: str | None = None) -> dict[str, Any]:
        """Every dependency the repo uses (LLMs, MCP servers, HTTP APIs, local programs), each with where it appears
        (file:line) and its latest health. Read from the code now; nothing is run."""
        r = pick(project)
        return r.answer("get_map", _map_data(r))

    @server.tool(annotations=READ)
    def get_flow(project: str | None = None) -> dict[str, Any]:
        """The order the code calls its dependencies (Python), from each entry point: every call with its file:line
        and time (measured by the last check, else an estimate), the if-decisions, which call waits for which, and
        the critical path: the chain that sets the total time, as written versus as early as inputs allow."""
        r = pick(project)
        return r.answer("get_flow", _flow_data(r.flow()))

    @server.tool(annotations=READ)
    def get_advice(project: str | None = None) -> dict[str, Any]:
        """Calls that don't need each other's results but wait for each other: how much running them together
        saves, the change written out when it is safe (lines now and could be), what to move by hand, and a prompt
        describing the whole change. FlowForge never applies it: you make the change and run the tests."""
        r = pick(project)
        return r.answer("get_advice", _advice_data(r.flow()))

    @server.tool(annotations=CHECKS)
    async def check_health(ids: list[str] | None = None, project: str | None = None) -> dict[str, Any]:
        """Check the dependencies now (all, or the ids from get_map), like the dashboard's Check now: one request
        without any key to an API, the model list of an LLM, an MCP server started and asked for its tools, a local
        program looked for. An MCP server starts only if the user already said yes to its exact command in the
        dashboard. Each result says why something is down and the likely fix."""
        r = pick(project)
        result = r.scan()
        deps = {d.id: d for d in result.dependencies if d.kind in CHECKABLE and d.status == "confirmed"}
        if ids is not None:
            unknown = sorted(set(ids) - set(deps))
            if unknown:
                raise ToolError(f"not a checkable dependency of this repo: {', '.join(unknown)} (see get_map)")
            deps = {i: deps[i] for i in ids}
        targets = [target_for(d, result) for d in deps.values()]
        yes = confirmed_commands(r.storage) if r.shared else set()
        waiting = [t for t in targets if starts_process(t) and command_text(t) not in yes]
        runnable = [t for t in targets if t not in waiting]
        rows = [{"id": t.id, "kind": t.kind, "status": "skipped", "summary": NOT_STARTED} for t in waiting]
        if runnable:
            node = CheckNode(r.transport)
            try:
                run = await run_workflow(check_workflow(runnable, str(r.root)), {"check": node}, use_cache=False)
            finally:
                await node.aclose()
            by_step = {s.id: s.params["target"] for s in check_workflow(runnable, str(r.root)).steps}
            for step_id, step in run.steps.items():
                if step.state == StepState.SUCCEEDED and isinstance(step.output, dict):
                    rows.append(step.output)
                else:
                    target = by_step[step_id]
                    rows.append({"id": target["id"], "kind": target["kind"], "status": "skipped",
                                 "summary": "The check couldn't run", "reason": step.error})
        rows.sort(key=lambda row: list(deps).index(row["id"]))
        if r.shared and rows:
            r.storage.add_checks(f"agent-{uuid.uuid4().hex[:12]}", rows)   # kept, like Check now (D24)
        summary = dict(Counter(row["status"] for row in rows))
        return r.answer("check_health", {"results": rows, "summary": summary,
                                         "kept": r.shared, "waiting_for_yes": [t.id for t in waiting]})

    @server.tool(annotations=READ)
    def get_security_findings(project: str | None = None) -> dict[str, Any]:
        """What in the repo is unsafe, read from the code now: keys written in code or MCP configs, APIs called over
        plain http, MCP servers with no pinned version or given the whole disk. Each finding has its file:line, the
        dependency it belongs to, a masked excerpt, the fix, and a prompt describing the change. Values are never
        shown. Catches known key formats and these patterns, not everything."""
        r = pick(project)
        return r.answer("get_security_findings", _security_data(r.scan()))

    @server.tool(annotations=READ)
    def get_keys(project: str | None = None) -> dict[str, Any]:
        """The keys the repo's code reads from its environment (names that look like keys), each with where it is
        read, the dependencies that use it, its status (saved in FlowForge, only in .env, or missing) and its mask
        (`ffkey://NAME`, D43). You never get a value and never need one: see `how`, then run the app with run_app."""
        r = pick(project)
        return r.answer("get_keys", _keys_data(r.root, r.scan()))

    @server.tool(annotations=ASK)
    def request_key(name: str, why: str, project: str | None = None) -> dict[str, Any]:
        """Ask the user for a key your change needs (D38), e.g. after adding Stripe: name="STRIPE_SECRET_KEY",
        why="for Stripe in pay.py". It shows first on FlowForge's Keys page. You never get or send the value: write
        code that reads the name from the environment (or write its mask, ffkey://NAME), tell the user to paste the key
        on the Keys page, then call wait_for_keys. Then run the app with run_app."""
        r = pick(project)
        if not NAME.fullmatch(name):
            raise ToolError("name must be an env var name: letters, digits and _, not starting with a digit")
        add_key_request(r.storage, r.root, name, why.strip() or "asked by your coding agent")
        saved = KeyStore(r.root).status([name], verify=False)[name] == "saved"
        if saved:
            clear_key_requests(r.storage, r.root, [name])
        where = "" if r.shared else " (open the dashboard on this repo: `flowforge --repo " + str(r.root) + "`)"
        return r.answer("request_key", {
            "name": name, "status": "saved" if saved else "requested",
            "message": f"{name} is saved already: use it." if saved else
            f"Ask the user to paste {name} on FlowForge's Keys page{where}; it's at the top. Then call wait_for_keys."})

    @server.tool(annotations=READ)
    async def wait_for_keys(names: list[str], seconds: int = 60, project: str | None = None) -> dict[str, Any]:
        """Wait until the user has saved these keys on the Keys page (D38): returns as soon as all are saved, or
        after `seconds` (at most 110; call again to keep waiting). Reads only which names are saved, never a
        value."""
        r = pick(project)
        import asyncio

        wanted = [n for n in dict.fromkeys(names) if NAME.fullmatch(n)]
        deadline = time.monotonic() + max(1, min(MAX_WAIT_S, int(seconds)))
        store = KeyStore(r.root)
        while True:
            status = store.status(wanted, verify=False)
            saved = [n for n in wanted if status[n] == "saved"]
            if len(saved) == len(wanted) or time.monotonic() >= deadline:
                break
            await asyncio.sleep(1)
        clear_key_requests(r.storage, r.root, saved)
        waiting = [n for n in wanted if n not in saved]
        return r.answer("wait_for_keys", {
            "saved": saved, "waiting": waiting, "done": not waiting,
            "message": "All saved: run the app with run_app." if not waiting else
            f"Still waiting for {', '.join(waiting)}: call wait_for_keys again, or remind the user."})

    @server.tool(annotations=RUN)
    async def run_app(command: list[str], wait_seconds: int = 60, project: str | None = None) -> dict[str, Any]:
        """Run the user's app (or build it) with its keys, through FlowForge (D43). `command` is the argument list,
        e.g. ["flutter", "run", "--dart-define=STRIPE_KEY=ffkey://STRIPE_KEY"] or ["npm", "run", "dev"]. Write a key's
        mask (from get_keys) wherever a value goes; code that reads the env var NAME gets it too. FlowForge fills
        every mask as the app starts; you never see a value, and the output comes back masked. The first time a
        command is used, the user must Allow it in FlowForge: this waits up to `wait_seconds` (at most 110); call
        again with the same command to keep waiting. Follow a run with app_output; stop it with stop_app."""
        import asyncio

        r = pick(project)
        if not command or not all(isinstance(a, str) and a for a in command):
            raise ToolError("command is the argument list, e.g. [\"npm\", \"run\", \"dev\"]")
        asked = (await ask_flowforge(r, "POST", "/apps/run", {"argv": command})).json()
        deadline = time.monotonic() + max(1, min(MAX_WAIT_S, int(wait_seconds)))
        while asked["state"] == "waiting" and time.monotonic() < deadline:
            await asyncio.sleep(1)
            request = (await ask_flowforge(r, "GET", f"/apps/requests/{asked['request']['id']}")).json()
            if request["state"] not in ("waiting", "starting"):
                asked = {"state": "running" if request["state"] == "allowed" else "denied", "run": request["run"],
                         "request": request}
        if asked["state"] in ("running", "failed") and (asked.get("run") or {}).get("status") == "failed":
            data = {"state": "failed", "run": asked["run"],
                    "message": f"It couldn't start: {asked['run'].get('error', 'unknown error')}"}
        elif asked["state"] == "running":
            data = {"state": "running", "run": asked["run"],
                    "message": "Started with its keys. Follow it with app_output; stop it with stop_app."}
        elif asked["state"] == "denied":
            data = {"state": "denied", "message": "The user denied this command in FlowForge. Ask them why first."}
        else:
            data = {"state": "waiting", "request": asked["request"]["id"],
                    "message": "Waiting for the user to Allow it in FlowForge (every page shows the request). Call "
                               "run_app again with the same command to keep waiting."}
        return r.answer("run_app", data)

    @server.tool(annotations=READ)
    async def app_output(run_id: str, since: int = 0, project: str | None = None) -> dict[str, Any]:
        """A run's output after line `since` (masked: a key's value shows as [REDACTED]), and whether it is still
        running, exited (with its code) or stopped."""
        r = pick(project)
        got = (await ask_flowforge(r, "GET", f"/apps/runs/{run_id}/output?since={max(0, int(since))}")).json()
        return r.answer("app_output", got)

    @server.tool(annotations=RUN)
    async def stop_app(run_id: str, project: str | None = None) -> dict[str, Any]:
        """Stop a run started with run_app."""
        r = pick(project)
        return r.answer("stop_app", (await ask_flowforge(r, "POST", f"/apps/runs/{run_id}/stop")).json())

    @server.tool(annotations=READ)
    def get_fix_requests(project: str | None = None) -> dict[str, Any]:
        """The issues the user sent you from FlowForge's Issues page ("do the FlowForge fixes"): each with its
        file:line, what is wrong, how to fix it and the whole change described (masked: no key value). An issue leaves
        the list once the code no longer has it, so call what_changed after your edit to confirm."""
        r = pick(project)
        return r.answer("get_fix_requests", _fix_requests_data(r))

    @server.tool(annotations=READ)
    def what_changed(project: str | None = None) -> dict[str, Any]:
        """After an edit: the dependencies added or removed since the map saved in the dashboard, and the flow's
        times now. Use it to confirm a change did what you meant."""
        r = pick(project)
        saved = r.storage.latest_flow_version("deps") if r.shared else None
        if saved is None or not saved.get("flow"):
            return r.answer("what_changed", {"saved": False, "message": "The dashboard has no saved map of this repo "
                                             f"yet: open it with `flowforge --repo {r.root}` first."})
        before = {n["id"]: n for n in saved["flow"]["nodes"] if n["kind"] in CALL_KINDS}
        result = r.scan()
        now = {d.id: d for d in result.dependencies}
        added = [{"id": d.id, "kind": d.kind, "name": d.name, "places": [e.ref for e in d.evidence]}
                 for i, d in now.items() if i not in before]
        removed = [{"id": i, "kind": n["kind"], "name": n["title"]} for i, n in before.items() if i not in now]
        flow = r.flow().flow
        return r.answer("what_changed", {"saved": True, "saved_version": saved["version"], "added": added,
                                         "removed": removed, "flow": _times(flow) if flow else None})

    return server
