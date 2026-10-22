"""Check now (D24): a health check of every dependency on the map, run by the scheduler, kept over time.

GET  /checks/plan           what a check run would do, the MCP servers it would start, and whether you said yes
POST /checks {ids?, confirm?}   start a check run (201, `run_id`); 409 until starting MCP servers is confirmed
GET  /checks                the latest verdict per dependency, in map order, with a summary
GET  /checks/{dep_id}       one dependency's checks, newest first

Progress streams over GET /runs/{run_id}/events, like any run (D16).
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from flowforge.api.runs import start_run
from flowforge.api.scan import repo_path
from flowforge.checks import CheckTarget, probes, starts_process
from flowforge.nodes.check_node import MCP_AT_ONCE
from flowforge.scan.models import Dependency, EnvName, ScanResult
from flowforge.scan.urls import clean_url
from flowforge.schema import Step, Workflow
from flowforge.state import AppState, app_state

router = APIRouter()

CHECKABLE = ("llm", "api", "mcp", "local")
CONFIRMED_SETTING = "checks_confirmed"   # the MCP commands the user agreed to start, one by one (JSON list)
LAST_RUN_SETTING = "checks_last_run"
HISTORY = 12                             # checks shown per dependency
COUNTS = ("up", "warn", "down", "skipped", "unchecked", "unconfirmed")
# rough check times by kind, so the scheduler starts the slow MCP servers first (D1 weights, D24)
ESTIMATE_MS = {"mcp": 3000.0, "llm": 300.0, "api": 300.0, "local": 10.0}
STEP_SLACK_S = 5.0   # on top of a probe's own timeout


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = None   # None = every dependency on the map
    confirm: bool = False          # yes, start the MCP servers listed in /checks/plan


def _reads_env(dep: Dependency, scan: ScanResult) -> list[EnvName]:
    """Env names an MCP server's own script reads, and where, from the scan (for a likely fix when it won't start)."""
    if dep.kind != "mcp" or not dep.command or len(dep.command) < 2:
        return []
    script = dep.command[1]
    return [e for e in scan.env_names if e.ref.rsplit(":", 1)[0] == script]


def _address(what: str | None) -> str | None:
    """A block you added: its text is an address only if it looks like one (no query kept, D24)."""
    if not what or " " in what.strip():
        return None
    what = what.strip()
    return clean_url(what) if "://" in what else (what if "." in what or ":" in what else None)


def target_for(dep: Dependency, scan: ScanResult, name: str | None = None) -> CheckTarget:
    """What a check of a scanned dependency reaches (D24); shared by Check now and the MCP server (D29)."""
    return CheckTarget(id=dep.id, kind=dep.kind, name=name or dep.name, target=dep.target, command=dep.command,
                       model=dep.model, catalog=dep.catalog, env_names=dep.env_names, reads_env=_reads_env(dep, scan))


def confirmed_commands(storage: Any) -> set[str]:
    """The MCP commands the user said yes to starting (D24)."""
    return set(json.loads(storage.setting(CONFIRMED_SETTING) or "[]"))


def _target(node: dict[str, Any], dep: Dependency | None, scan: ScanResult | None) -> CheckTarget:
    if dep is not None and scan is not None:
        return target_for(dep, scan, node["title"])
    what = (node.get("what") or "").strip()   # a dependency the user added on the map: its address or command
    address = _address(what)
    if node["kind"] in ("mcp", "local") and what and "://" not in what:
        command = what.split()
    else:
        command = [address] if node["kind"] == "mcp" and address else None
    return CheckTarget(id=node["id"], kind=node["kind"], name=node["title"], catalog=node.get("catalog"),
                       target=address, command=command, model=(node.get("op") or {}).get("model"))


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


def command_text(t: CheckTarget) -> str:
    return " ".join(t.command or [])


def _confirmed(s: AppState) -> set[str]:
    return confirmed_commands(s.storage)


def _unconfirmed(s: AppState, targets: list[CheckTarget]) -> list[CheckTarget]:
    """The servers this check would start that the user hasn't said yes to. Each yes covers the command shown, so
    a re-scan or an edit that changes a command asks again (D24). Example mode starts nothing."""
    if s.example:
        return []
    yes = _confirmed(s)
    return [t for t in targets if starts_process(t) and command_text(t) not in yes]


def check_workflow(targets: list[CheckTarget], root: str) -> Workflow:
    """One check step per dependency, no edges, no retries, no cache (D24). Only MCP_AT_ONCE servers start
    together (CheckNode), so a server's timeout includes its wait for a turn: every round may take the full
    MCP_TIMEOUT_S."""
    rounds = math.ceil(sum(t.kind == "mcp" for t in targets) / MCP_AT_ONCE) or 1
    timeout = {"mcp": probes.MCP_TIMEOUT_S * rounds, "llm": probes.HTTP_TIMEOUT_S, "api": probes.HTTP_TIMEOUT_S,
               "local": 1.0}
    steps = [Step(id="c_" + re.sub(r"\W", "_", t.id), type="check", retries=0, cache=False,
                  description=f"Check {t.name}", estimated_ms=ESTIMATE_MS[t.kind],
                  timeout_s=timeout[t.kind] + STEP_SLACK_S,
                  params={"target": t.model_dump(mode="json"), "root": root}) for t in targets]
    return Workflow(id="health-check", name="Health check", max_concurrency=8, type_concurrency={"check": 8},
                    steps=steps)


@router.get("/checks/plan")
def check_plan() -> dict[str, Any]:
    s = app_state()
    _, targets, deps = _map(s)
    root = repo_path(s)
    starts = []
    for t in targets.values():
        if starts_process(t):
            dep = deps.get(t.id)
            source = dep.evidence[0].ref if dep and dep.evidence else None
            starts.append({"id": t.id, "name": t.name, "command": " ".join(t.command or []),
                           "origin": _origin(t.command or [], root), "source": source})
    confirmed = not _unconfirmed(s, list(targets.values()))
    kinds = {k: sum(t.kind == k for t in targets.values()) for k in CHECKABLE}
    return {"checks": len(targets), "kinds": kinds, "starts": starts, "confirmed": confirmed, "example": s.example}


async def _record(s: AppState, run_id: str, workflow: Workflow) -> None:
    """When the run ends, keep a verdict for every check that finished (D24), from the run's events, so a run you
    stopped still keeps what it found. A check that broke says so (skipped), never blaming the dependency; a
    check that never ran records nothing."""
    run = s.runs[run_id]
    if run.task is not None:
        await asyncio.wait([run.task])
    targets = {step.id: step.params["target"] for step in workflow.steps}
    rows = []
    for event in run.events:
        if event.get("type") != "step" or event.get("step_id") not in targets:
            continue
        out = event.get("output")
        if event.get("state") == "succeeded" and isinstance(out, dict) and out.get("status"):
            rows.append(out)
        elif event.get("state") == "failed":
            target = targets[event["step_id"]]
            rows.append({"id": target["id"], "kind": target["kind"], "status": "skipped",
                         "summary": "The check couldn't run", "reason": event.get("error")})
    if rows:
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
    asking = _unconfirmed(s, chosen)
    if asking:
        if not req.confirm:
            n = len(asking)
            raise HTTPException(409, f"Checking would start {n} MCP server{'s' if n != 1 else ''} on this computer. "
                                     "See what starts in GET /checks/plan, then send confirm: true.")
        # the yes covers exactly the servers this check starts, nothing else on the map
        s.storage.set_setting(CONFIRMED_SETTING, json.dumps(sorted(_confirmed(s) | {command_text(t) for t in asking})))
    workflow = check_workflow(chosen, str(root))
    run_id = start_run(workflow, use_cache=False)
    task = asyncio.create_task(_record(s, run_id, workflow))
    s.tasks.add(task)
    task.add_done_callback(s.tasks.discard)
    return {"run_id": run_id, "checks": len(workflow.steps)}


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
    run_id = s.storage.setting(LAST_RUN_SETTING)
    last = s.storage.get_run(run_id) if run_id else None
    return {"run_id": run_id, "checked_at": max(checked) if checked else None,
            "took_ms": last.get("makespan_ms") if last else None,
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
