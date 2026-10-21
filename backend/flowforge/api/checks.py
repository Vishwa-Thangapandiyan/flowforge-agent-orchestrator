"""Check now (D24): a health check of every dependency on the map, run by the scheduler, kept over time.

GET  /checks/plan           what a check run would do, the MCP servers it would start, and whether you said yes
POST /checks {ids?, confirm?}   start a check run (201, `run_id`); 409 until starting MCP servers is confirmed
GET  /checks                the latest verdict per dependency, in map order, with a summary
GET  /checks/{dep_id}       one dependency's checks, newest first

Progress streams over GET /runs/{run_id}/events, like any run (D16).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from flowforge.api.runs import start_run
from flowforge.api.scan import repo_path
from flowforge.checks import CheckTarget
from flowforge.flowmap.planner import fact_hash
from flowforge.scan.models import Dependency, ScanResult
from flowforge.schema import Step, Workflow
from flowforge.security.logfilter import REDACTED
from flowforge.state import AppState, app_state

router = APIRouter()

CHECKABLE = ("llm", "api", "mcp", "local")
CONFIRMED_SETTING = "checks_confirmed"   # the hash of the MCP commands the user agreed to start
LAST_RUN_SETTING = "checks_last_run"
HISTORY = 12                             # checks shown per dependency
COUNTS = ("up", "warn", "down", "skipped", "unchecked", "unconfirmed")
# rough check times by kind, so the scheduler starts the slow MCP servers first (D1 weights, D24)
ESTIMATE_MS = {"mcp": 3000.0, "llm": 300.0, "api": 300.0, "local": 10.0}


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = None   # None = every dependency on the map
    confirm: bool = False          # yes, start the MCP servers listed in /checks/plan


def _reads_env(dep: Dependency, scan: ScanResult) -> list[str]:
    """Env names an MCP server's own script reads, from the scan (for a likely fix when it won't start)."""
    if dep.kind != "mcp" or not dep.command or len(dep.command) < 2:
        return []
    script = dep.command[1]
    return sorted({e.name for e in scan.env_names if e.ref.rsplit(":", 1)[0] == script})


def _target(node: dict[str, Any], dep: Dependency | None, scan: ScanResult | None) -> CheckTarget:
    if dep is not None and scan is not None:
        return CheckTarget(id=dep.id, kind=dep.kind, name=node["title"], target=dep.target, command=dep.command,
                           model=dep.model, catalog=dep.catalog, env_names=dep.env_names,
                           reads_env=_reads_env(dep, scan))
    what = node.get("what") or None   # a dependency the user added on the map: its address or command
    stdio = node["kind"] in ("mcp", "local") and what and "://" not in what
    return CheckTarget(id=node["id"], kind=node["kind"], name=node["title"], catalog=node.get("catalog"),
                       target=None if stdio else what, command=what.split() if stdio else ([what] if what else None),
                       model=(node.get("op") or {}).get("model"))


def _map(s: AppState) -> tuple[list[dict[str, Any]], dict[str, CheckTarget], dict[str, Dependency]]:
    """The checkable blocks of the dependency map with your edits (hidden ones are gone), and their targets."""
    view = s.flows["deps"].current("mine")
    if not view.get("available"):
        return [], {}, {}
    analysis = s.flows["deps"].analysis() or {}
    scan = ScanResult.model_validate(analysis["scan"]) if analysis.get("scan") else None
    deps = {d.id: d for d in scan.dependencies} if scan else {}
    nodes = [n for n in view["nodes"] if n["kind"] in CHECKABLE]
    targets = {n["id"]: _target(n, deps.get(n["id"]), scan) for n in nodes if n["status"] != "unconfirmed"}
    return nodes, targets, deps


def _starts(t: CheckTarget) -> bool:
    """Checking this one starts a process: a stdio MCP server whose arguments are all known (D24)."""
    return (t.kind == "mcp" and bool(t.command) and "://" not in t.command[0]
            and not any(REDACTED in part for part in t.command))


def _origin(command: list[str], root: Path | None) -> str:
    """Where the code that starts comes from, in plain words."""
    program = Path(command[0]).name
    package = next((a for a in command[1:] if not a.startswith("-")), "")
    if program in ("npx", "bunx", "pnpx"):
        return "downloads from npm" + ("" if package.rfind("@") > 0 else ", any version")
    if program in ("uvx", "pipx"):
        return "downloads from PyPI" + ("" if "@" in package or "==" in package else ", any version")
    if root is not None and package and (root / package).is_file():
        return "runs a script in this repo"
    return f"runs {program} from your PATH"


def _confirm_key(targets: list[CheckTarget]) -> str:
    return fact_hash(sorted(" ".join(t.command or []) for t in targets if _starts(t)))


@router.get("/checks/plan")
def check_plan() -> dict[str, Any]:
    s = app_state()
    _, targets, deps = _map(s)
    root = repo_path(s)
    starts = []
    for t in targets.values():
        if _starts(t):
            dep = deps.get(t.id)
            source = dep.evidence[0].ref if dep and dep.evidence else None
            starts.append({"id": t.id, "name": t.name, "command": " ".join(t.command or []),
                           "origin": _origin(t.command or [], root), "source": source})
    confirmed = s.example or not starts or s.storage.setting(CONFIRMED_SETTING) == _confirm_key(list(targets.values()))
    kinds = {k: sum(t.kind == k for t in targets.values()) for k in CHECKABLE}
    return {"checks": len(targets), "kinds": kinds, "starts": starts, "confirmed": confirmed, "example": s.example}


async def _record(s: AppState, run_id: str, workflow: Workflow) -> None:
    """When the run ends, keep one verdict per dependency (D24). A step that crashed is a check that couldn't run."""
    run = s.runs[run_id]
    if run.task is not None:
        await asyncio.wait([run.task])
    steps = (run.result or {}).get("steps", {})
    rows = []
    for step in workflow.steps:
        target = step.params["target"]
        out = steps.get(step.id, {}).get("output")
        if isinstance(out, dict) and out.get("status"):
            rows.append(out)
        else:
            rows.append({"id": target["id"], "kind": target["kind"], "status": "down",
                         "summary": "The check couldn't run", "reason": steps.get(step.id, {}).get("error")})
    s.storage.add_checks(run_id, rows)
    s.storage.set_setting(LAST_RUN_SETTING, run_id)


@router.post("/checks", status_code=201)
async def start_checks(req: CheckRequest) -> dict[str, Any]:
    s = app_state()
    _, targets, _ = _map(s)
    root = repo_path(s)
    if not targets or root is None:
        raise HTTPException(409, "There is nothing to check yet. Scan a folder first.")
    chosen = list(targets.values())
    if req.ids is not None:
        unknown = sorted(set(req.ids) - set(targets))
        if unknown:
            raise HTTPException(422, f"not on the map, or unconfirmed: {', '.join(unknown)}")
        chosen = [targets[i] for i in req.ids]
    starting = [t for t in chosen if _starts(t)]
    key = _confirm_key(list(targets.values()))
    if starting and not s.example and s.storage.setting(CONFIRMED_SETTING) != key:
        if not req.confirm:
            n = len(starting)
            raise HTTPException(409, f"Checking would start {n} MCP server{'s' if n != 1 else ''} on this computer. "
                                     "See what starts in GET /checks/plan, then send confirm: true.")
        s.storage.set_setting(CONFIRMED_SETTING, key)
    steps = [Step(id="c_" + re.sub(r"\W", "_", t.id), type="check", retries=0, cache=False,
                  description=f"Check {t.name}", estimated_ms=ESTIMATE_MS[t.kind],
                  params={"target": t.model_dump(mode="json"), "root": str(root)}) for t in chosen]
    workflow = Workflow(id="health-check", name="Health check", max_concurrency=8, type_concurrency={"check": 8},
                        steps=steps)
    run_id = start_run(workflow, use_cache=False)
    task = asyncio.create_task(_record(s, run_id, workflow))
    s.tasks.add(task)
    task.add_done_callback(s.tasks.discard)
    return {"run_id": run_id, "checks": len(steps)}


def _item(node: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    item = {"id": node["id"], "name": node["title"], "kind": node["kind"], "catalog": node.get("catalog"),
            "history": [h["status"] for h in reversed(history)]}   # oldest first, as the squares read
    if node["status"] == "unconfirmed":
        return {**item, "status": "unconfirmed", "summary": "Not checked: unconfirmed", "history": []}
    if not history:
        return {**item, "status": "unchecked", "summary": "Not checked yet"}
    last = history[0]
    return {**item, **{k: last.get(k) for k in ("status", "latency_ms", "summary", "reason", "fix", "at")}}


@router.get("/checks")
def latest_checks() -> dict[str, Any]:
    s = app_state()
    nodes, _, _ = _map(s)
    by_dep: dict[str, list[dict[str, Any]]] = {}
    for row in s.storage.check_history(limit=HISTORY):
        by_dep.setdefault(row["dep_id"], []).append(row)
    items = [_item(n, by_dep.get(n["id"], [])) for n in nodes]
    summary = {k: sum(i["status"] == k for i in items) for k in COUNTS}
    checked = [i["at"] for i in items if i.get("at")]
    return {"run_id": s.storage.setting(LAST_RUN_SETTING), "checked_at": max(checked) if checked else None,
            "summary": summary, "items": items, "example": s.example}


@router.get("/checks/{dep_id}")
def dependency_checks(dep_id: str, limit: int = 50) -> list[dict[str, Any]]:
    s = app_state()
    nodes, _, _ = _map(s)
    history = s.storage.check_history(dep_id, limit=limit)
    if not history and dep_id not in {n["id"] for n in nodes}:
        raise HTTPException(404, f"'{dep_id}' isn't on the map")
    return [{k: h.get(k) for k in ("run_id", "status", "latency_ms", "summary", "reason", "fix", "at")}
            for h in history]
