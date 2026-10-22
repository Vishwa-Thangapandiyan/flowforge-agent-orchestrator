"""FlowForge as an MCP server (D28, D29): five read-only tools a coding agent can ask about the repo it works in.

The map and the flow are read fresh from the repo on every call (plain code, nothing run, no LLM: D20). The
dashboard's database supplies what only it knows, when it maps the same repo: measured latencies, past checks,
the user's yes to starting MCP servers, and the saved map to compare with. Every answer is masked (D22).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from flowforge.api.checks import CHECKABLE, check_workflow, command_text, confirmed_commands, target_for
from flowforge.api.scan import REPO_SETTING
from flowforge.checks import starts_process
from flowforge.connectors.registry import Registry
from flowforge.flow import flow_of
from flowforge.flowmap.models import CALL_KINDS, Flow
from flowforge.flowmap.validate import code_writes, critical
from flowforge.nodes.check_node import CheckNode
from flowforge.scan import ScanResult, scan
from flowforge.scheduler.executor import StepState, run_workflow
from flowforge.security.logfilter import Redactor, redact_code, secret_values_for
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
    "LLM. Answers are masked: key values never appear. It never edits code: you make the change, then call "
    "what_changed to confirm."
)
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
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
    security = _security_data(read.scan or r.scan())
    worst = next((lv for lv in ("high", "medium", "low") if security["summary"].get(lv)), None)
    cards = [
        {"tool": "get_map", "headline": headline("get_map", deps), "sub": kinds, "tone": "plain"},
        {"tool": "check_health", "headline": headline("check_health", health) if checked else "Not checked yet",
         "sub": f"{_plural(len(checked), 'last check')} stored" if checked else "Your agent can run the checks",
         "tone": tone},
        {"tool": "get_security_findings", "headline": headline("get_security_findings", security),
         "sub": "keys in code, plain http, risky MCP servers",
         "tone": {"high": "bad", "medium": "warn"}.get(worst or "", "ok")},
        {"tool": "get_flow", "headline": headline("get_flow", flow) if flow["available"] else None,
         "sub": "as written → could be" if flow["available"] else flow["message"], "tone": "plain"},
        {"tool": "get_advice", "headline": (_plural(len(advice["advice"]), "way") + " to be faster")
         if advice["available"] else None,
         "sub": f"saves ~{_seconds(advice['saved_ms'])}, the change written out" if advice["available"] else None,
         "tone": "warn" if advice["available"] and advice["advice"] else "plain"},
        {"tool": "what_changed", "headline": None, "sub": "After your agent edits: what it added or removed",
         "tone": "plain"},
    ]
    return _mask({"repo": r.root.name, "cards": cards}, r.redactor)


def build_server(repo: Path, storage: Storage, *, transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    """The server for one repo. `transport` answers the health checks' requests in tests."""
    r = _Repo(repo, storage, transport)
    server = MCPServer(name="flowforge", title="FlowForge", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ)
    def get_map() -> dict[str, Any]:
        """Every dependency the repo uses (LLMs, MCP servers, HTTP APIs, local programs), each with where it appears
        (file:line) and its latest health. Read from the code now; nothing is run."""
        return r.answer("get_map", _map_data(r))

    @server.tool(annotations=READ)
    def get_flow() -> dict[str, Any]:
        """The order the code calls its dependencies (Python), from each entry point: every call with its file:line
        and time (measured by the last check, else an estimate), the if-decisions, which call waits for which, and
        the critical path: the chain that sets the total time, as written versus as early as inputs allow."""
        return r.answer("get_flow", _flow_data(r.flow()))

    @server.tool(annotations=READ)
    def get_advice() -> dict[str, Any]:
        """Calls that don't need each other's results but wait for each other: how much running them together
        saves, the change written out when it is safe (lines now and could be), what to move by hand, and a prompt
        describing the whole change. FlowForge never applies it: you make the change and run the tests."""
        return r.answer("get_advice", _advice_data(r.flow()))

    @server.tool(annotations=CHECKS)
    async def check_health(ids: list[str] | None = None) -> dict[str, Any]:
        """Check the dependencies now (all, or the ids from get_map), like the dashboard's Check now: one request
        without any key to an API, the model list of an LLM, an MCP server started and asked for its tools, a local
        program looked for. An MCP server starts only if the user already said yes to its exact command in the
        dashboard. Each result says why something is down and the likely fix."""
        result = r.scan()
        deps = {d.id: d for d in result.dependencies if d.kind in CHECKABLE and d.status == "confirmed"}
        if ids is not None:
            unknown = sorted(set(ids) - set(deps))
            if unknown:
                raise ValueError(f"not a checkable dependency of this repo: {', '.join(unknown)} (see get_map)")
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
    def get_security_findings() -> dict[str, Any]:
        """What in the repo is unsafe, read from the code now: keys written in code or MCP configs, APIs called over
        plain http, MCP servers with no pinned version or given the whole disk. Each finding has its file:line, the
        dependency it belongs to, a masked excerpt, the fix, and a prompt describing the change. Values are never
        shown. Catches known key formats and these patterns, not everything."""
        return r.answer("get_security_findings", _security_data(r.scan()))

    @server.tool(annotations=READ)
    def what_changed() -> dict[str, Any]:
        """After an edit: the dependencies added or removed since the map saved in the dashboard, and the flow's
        times now. Use it to confirm a change did what you meant."""
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
