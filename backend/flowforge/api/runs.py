"""Runs: validate, start, list, inspect, stream, stop (D7, D12, D16).

POST /validate                 workflow JSON → {"ok", "order", "levels", "critical_path", "warnings"} or 422
POST /runs?policy=&use_cache=  workflow JSON → {"run_id", "warnings"}; the run executes in the background
GET  /runs?status=&limit=&before=  run summaries, newest first
GET  /runs/{run_id}            → {"status", "error", "result", "summary"}; served from storage after a restart
GET  /runs/{run_id}/events     → Server-Sent Events, replayed from the start (live or stored)
POST /runs/{run_id}/stop       → cancels a running run
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.sse import EventSourceResponse, ServerSentEvent

from flowforge.nodes.base import NodeError, TransientNodeError, current_run_id
from flowforge.nodes.mcp_node import MCPNode, check_call
from flowforge.scheduler import graph
from flowforge.scheduler.critical_path import critical_path
from flowforge.scheduler.durations import estimate_weights
from flowforge.scheduler.executor import POLICIES, Policy, check_nodes, run_workflow
from flowforge.schema import Workflow
from flowforge.state import Run, app_state, plain
from flowforge.templating import referenced_steps

MCP_CHECK_TIMEOUT_S = 5  # pre-run tool discovery; slower servers get a warning instead (D12)

router = APIRouter()


def check_graph(workflow: Workflow) -> graph.DAG:
    try:
        dag = graph.build_dag(workflow)
        check_nodes(workflow, app_state().nodes)  # unknown connector, type mismatch, bad fallback (D10)
    except (graph.CycleError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return dag


async def check_mcp_calls(workflow: Workflow) -> list[str]:
    """Check each MCP step's tool and literal arguments against its server before a run (D12).

    A wrong call → 422 with the reason. An unreachable server → a warning; the step is
    still checked when it runs. Templated arguments are checked at run time only.
    """
    nodes = app_state().nodes
    errors: list[str] = []
    warnings: list[str] = []
    for step in workflow.steps:
        node = nodes.get(step.connector or step.type)
        tool = step.params.get("tool")
        if step.type != "mcp" or not isinstance(node, MCPNode) or not isinstance(tool, str) or referenced_steps(tool):
            continue
        arguments = step.params.get("arguments", {})
        try:
            tools = await asyncio.wait_for(node.list_tools(step.params.get("server")), MCP_CHECK_TIMEOUT_S)
        except (TransientNodeError, TimeoutError) as exc:
            warnings.append(f"step '{step.id}': could not reach the MCP server to check tool '{tool}' "
                            f"({str(exc) or type(exc).__name__}); it will be checked when the step runs")
            continue
        except NodeError as exc:
            errors.append(f"step '{step.id}': {exc}")
            continue
        problem = check_call(tools, tool, None if referenced_steps(arguments) else arguments)
        if problem:
            errors.append(f"step '{step.id}': {problem}")
    if errors:
        raise HTTPException(422, "; ".join(errors))
    return warnings


# --- run summaries (D16) ---------------------------------------------------------------------------

def totals(result: dict[str, Any]) -> dict[str, Any]:
    """Per-run numbers for history and savings, from a (redacted) RunResult dict."""
    tokens = 0
    credits = 0.0
    work_ms = 0.0
    for step in result["steps"].values():
        if step["started_at"] is not None and step["finished_at"] is not None:
            work_ms += (step["finished_at"] - step["started_at"]) * 1000
        usage = step["output"].get("usage") if isinstance(step["output"], dict) else None
        if isinstance(usage, dict) and not step["cache_hit"]:
            tokens += int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
            credits += float(usage.get("credits") or 0)
    return {"makespan_ms": result["makespan_ms"], "api_calls": result["api_calls"],
            "cache_hits": result["cache_hits"], "tokens": tokens, "credits": credits, "work_ms": work_ms}


def failure_reason(workflow: Workflow, result: dict[str, Any]) -> str | None:
    """The first failure in plain words, and how many later steps it skipped."""
    steps = result["steps"]
    failed = sorted((s for s in steps.values() if s["state"] == "failed"), key=lambda s: s["finished_at"] or 0)
    if not failed:
        return None
    first = failed[0]
    step = workflow.step(first["step_id"])
    title = step.description or step.id
    dag = graph.build_dag(workflow)
    skipped = sum(1 for d in graph.descendants(dag, step.id) if steps[d]["state"] == "skipped")
    text = f'Step "{title}" failed: {first["error"]}.'
    if skipped:
        text += f" {skipped} step{'s' if skipped != 1 else ''} after it {'were' if skipped != 1 else 'was'} skipped."
    if len(failed) > 1:
        text += f" {len(failed) - 1} other step{'s' if len(failed) > 2 else ''} also failed."
    return text


# a step with no connector runs on its type's default; these are the connectors behind them (D10)
DEFAULT_CONNECTOR = {"llm": "nim", "mcp": "fetch"}


def outline(workflow: Workflow) -> list[dict[str, Any]]:
    """What the dashboard needs to draw a run: no params, which could hold anything."""
    return [{"id": s.id, "title": s.description or s.id, "type": s.type, "connector": s.connector,
             "depends_on": list(s.depends_on)} for s in workflow.steps]


def connectors_used(steps: list[dict[str, Any]]) -> list[str]:
    used: list[str] = []
    for step in steps:
        connector = step["connector"] or DEFAULT_CONNECTOR.get(step["type"])
        if connector and connector not in used:
            used.append(connector)
    return used


def summary(row: dict[str, Any], live: Run | None = None) -> dict[str, Any]:
    status = live.status if live is not None else row["status"]
    steps = json.loads(row["steps_json"]) if row.get("steps_json") else []
    return {
        "id": row["id"], "plan": row["workflow_name"] or row["workflow_id"], "workflow_id": row["workflow_id"],
        "status": status, "policy": row["policy"], "started_at": row["started_at"],
        "finished_at": row["finished_at"], "time_ms": row["makespan_ms"], "api_calls": row["api_calls"],
        "cache_hits": row["cache_hits"], "tokens": row["tokens"], "credits": row["credits"],
        "work_ms": row["work_ms"], "failure_reason": row["failure_reason"], "connectors": connectors_used(steps),
    }


# --- routes ----------------------------------------------------------------------------------------

@router.post("/validate")
async def validate(workflow: Workflow) -> dict[str, Any]:
    dag = check_graph(workflow)
    warnings = await check_mcp_calls(workflow)
    s = app_state()
    weights = estimate_weights(workflow, s.storage.duration_history(workflow.id))
    cp = critical_path(dag, weights)
    return {
        "ok": True,
        "order": graph.topological_order(dag),
        "levels": graph.levels(dag),
        "weights": weights,
        "critical_path": cp.path,
        "critical_path_ms": cp.length_ms,
        "warnings": warnings,
    }


@router.post("/runs")
async def create_run(workflow: Workflow, policy: Policy = "critical_path", use_cache: bool = True) -> dict[str, Any]:
    if policy not in POLICIES:
        raise HTTPException(422, f"policy must be one of {POLICIES}")
    check_graph(workflow)
    warnings = await check_mcp_calls(workflow)
    return {"run_id": start_run(workflow, policy=policy, use_cache=use_cache), "warnings": warnings}


def start_run(workflow: Workflow, *, policy: Policy = "critical_path", use_cache: bool = True,
              started_at: datetime | None = None) -> str:
    """Start `workflow` in the background; it is recorded from its first event (D16).

    `started_at` back-dates the stored run (example-data history only).
    """
    s = app_state()
    run_id = uuid.uuid4().hex[:12]
    s.storage.start_run(run_id, workflow.id, workflow.name or workflow.id, policy,
                        started_at.isoformat(timespec="milliseconds") if started_at else None, outline(workflow))
    run = s.runs[run_id] = Run(run_id, workflow, s.storage, s.redactor)
    # a snapshot: editing a connector mid-run never swaps a node out from under this run (D16)
    nodes, buckets = dict(s.nodes), dict(s.rate_limits)

    def finish(status: str, result: dict[str, Any] | None, reason: str | None) -> None:
        run.status, run.result = status, result
        finished_at = None
        if started_at is not None:
            elapsed = timedelta(milliseconds=result["makespan_ms"]) if result else timedelta()
            finished_at = (started_at + elapsed).isoformat(timespec="milliseconds")
        s.storage.finish_run(run_id, status, result, totals(result) if result else {}, reason, finished_at)

    async def execute() -> None:
        current_run_id.set(run_id)  # artifact folder for this run's large outputs (D12)
        try:
            raw = await run_workflow(
                workflow, nodes, policy=policy, use_cache=use_cache,
                rate_limits=buckets, storage=s.storage, on_event=run.push,
            )
            result = plain(asdict(raw), s.redactor)
            finish(raw.status, result, failure_reason(workflow, result))
        except asyncio.CancelledError:
            status = "interrupted" if s.shutting_down else "stopped"
            reason = "The server stopped while this was running." if s.shutting_down else "Stopped by you."
            run.push({"type": "run", "state": status})
            finish(status, None, reason)
        except Exception as exc:  # validation passed, so this is an engine bug — surface it
            run.error = s.redactor.redact_text(f"{type(exc).__name__}: {exc}")
            run.push({"type": "run", "state": "error", "error": run.error})
            finish("error", None, run.error)
        finally:
            run.done = True
            run.changed.set()

    run.task = asyncio.create_task(execute())
    s.tasks.add(run.task)
    run.task.add_done_callback(s.tasks.discard)
    return run_id


@router.get("/runs")
def list_runs(status: str | None = None, limit: int = Query(50, ge=1, le=500),
              before: str | None = None) -> list[dict[str, Any]]:
    s = app_state()
    return [summary(row, s.runs.get(row["id"])) for row in s.storage.list_runs(status, limit, before)]


@router.get("/runs/{run_id}")
def run_status(run_id: str) -> dict[str, Any]:
    s = app_state()
    row = s.storage.get_run(run_id)
    if row is None:
        raise HTTPException(404, "unknown run")
    live = s.runs.get(run_id)
    steps = json.loads(row["steps_json"]) if row.get("steps_json") else []
    if live is not None:
        return {"status": live.status, "error": live.error, "result": live.result, "summary": summary(row, live),
                "steps": steps}
    return {"status": row["status"], "error": row["failure_reason"] if row["status"] == "error" else None,
            "result": row["result"], "summary": summary(row), "steps": steps}


@router.get("/runs/{run_id}/events", response_class=EventSourceResponse)
async def run_events(run_id: str) -> AsyncIterator[ServerSentEvent]:
    s = app_state()
    run = s.runs.get(run_id)
    if run is None:  # finished before this server started: replay what was stored
        if s.storage.get_run(run_id) is None:
            raise HTTPException(404, "unknown run")
        for seq, event in enumerate(s.storage.run_events(run_id)):
            yield ServerSentEvent(data=jsonable_encoder(event), id=str(seq))
        yield ServerSentEvent(data={"type": "end"}, event="end")
        return
    sent = 0
    while True:
        run.changed.clear()
        while sent < len(run.events):
            yield ServerSentEvent(data=jsonable_encoder(run.events[sent]), id=str(sent))
            sent += 1
        if run.done:
            yield ServerSentEvent(data={"type": "end"}, event="end")
            return
        await run.changed.wait()


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str) -> dict[str, str]:
    s = app_state()
    run = s.runs.get(run_id)
    if run is None:
        if s.storage.get_run(run_id) is None:
            raise HTTPException(404, "unknown run")
        raise HTTPException(409, "this run is not running")
    if run.done or run.task is None:
        raise HTTPException(409, "this run is not running")
    run.task.cancel()
    return {"status": "stopping"}
