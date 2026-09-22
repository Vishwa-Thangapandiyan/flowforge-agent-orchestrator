"""FastAPI app. Owner: Person C.

POST /validate               workflow JSON → {"ok", "order", "levels", "critical_path"} or 422
POST /runs?policy=&use_cache= workflow JSON → {"run_id"}; the run executes in the background
GET  /runs/{run_id}          → {"status", "result"}
GET  /runs/{run_id}/events   → Server-Sent Events: every executor event, replayed from the start
GET  /workflows              → names of the example workflows
GET  /workflows/{name}       → one example workflow's JSON
GET  /                       → the status page (frontend/index.html)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from flowforge.nodes.base import Node
from flowforge.nodes.http_node import HTTPNode
from flowforge.nodes.llm_node import LLMNode
from flowforge.nodes.mcp_node import MCPNode
from flowforge.nodes.mock_node import MockNode
from flowforge.schema import Workflow
from flowforge.scheduler import graph
from flowforge.scheduler.critical_path import critical_path
from flowforge.scheduler.durations import estimate_weights
from flowforge.scheduler.executor import POLICIES, Event, Policy, RunResult, run_workflow
from flowforge.scheduler.rate_limit import TokenBucket
from flowforge.storage import Storage

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / "backend" / "workflows"
FRONTEND = ROOT / "frontend" / "index.html"


@dataclass
class Run:
    workflow: Workflow
    events: list[Event] = field(default_factory=list)
    result: RunResult | None = None
    error: str | None = None
    done: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, event: Event) -> None:
        self.events.append(event)
        self.changed.set()


@dataclass
class AppState:
    nodes: dict[str, Node]
    rate_limits: dict[str, TokenBucket]
    storage: Storage
    runs: dict[str, Run] = field(default_factory=dict)
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)


state: AppState | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global state
    state = AppState(
        nodes={"llm": LLMNode(), "http": HTTPNode(), "mcp": MCPNode(), "mock": MockNode()},
        rate_limits={"nim": TokenBucket(float(os.getenv("NIM_RPM", "40")))},
        storage=Storage(os.getenv("FLOWFORGE_DB", ROOT / "flowforge.db")),
    )
    yield
    for task in state.tasks:
        task.cancel()
    for node in state.nodes.values():
        await node.aclose()


app = FastAPI(title="FlowForge", lifespan=lifespan)


def app_state() -> AppState:
    assert state is not None, "app not started"
    return state


def check_graph(workflow: Workflow) -> graph.DAG:
    try:
        return graph.build_dag(workflow)
    except graph.CycleError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/validate")
async def validate(workflow: Workflow) -> dict[str, Any]:
    dag = check_graph(workflow)
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
    }


@app.post("/runs")
async def create_run(workflow: Workflow, policy: Policy = "critical_path", use_cache: bool = True) -> dict[str, str]:
    if policy not in POLICIES:
        raise HTTPException(422, f"policy must be one of {POLICIES}")
    check_graph(workflow)
    s = app_state()
    run_id = uuid.uuid4().hex[:12]
    run = s.runs[run_id] = Run(workflow)

    async def execute() -> None:
        try:
            run.result = await run_workflow(
                workflow, s.nodes, policy=policy, use_cache=use_cache,
                rate_limits=s.rate_limits, storage=s.storage, on_event=run.push,
            )
            s.storage.save_run(run_id, run.result)
        except Exception as exc:  # validation passed, so this is an engine bug — surface it
            run.error = f"{type(exc).__name__}: {exc}"
            run.push({"type": "run", "state": "error", "error": run.error})
        finally:
            run.done = True
            run.changed.set()

    task = asyncio.create_task(execute())
    s.tasks.add(task)
    task.add_done_callback(s.tasks.discard)
    return {"run_id": run_id}


def get_run(run_id: str) -> Run:
    run = app_state().runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return run


@app.get("/runs/{run_id}")
def run_status(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    status = "error" if run.error else (run.result.status if run.result else "running")
    return {
        "status": status,
        "error": run.error,
        "result": jsonable_encoder(asdict(run.result)) if run.result else None,
    }


@app.get("/runs/{run_id}/events", response_class=EventSourceResponse)
async def run_events(run_id: str) -> AsyncIterator[ServerSentEvent]:
    run = get_run(run_id)
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


@app.get("/workflows")
def list_workflows() -> list[str]:
    return sorted(p.stem for p in WORKFLOWS_DIR.glob("*.json"))


@app.get("/workflows/{name}")
def get_workflow(name: str) -> dict[str, Any]:
    path = WORKFLOWS_DIR / f"{name}.json"
    if path.parent != WORKFLOWS_DIR or not path.exists():
        raise HTTPException(404, "unknown workflow")
    return json.loads(path.read_text())


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND)
