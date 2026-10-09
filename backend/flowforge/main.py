"""FastAPI app: start-up wiring and small routes. Runs: api/runs.py. Connectors: api/connectors.py.

GET  /workflows              → names of the example workflows
GET  /workflows/{name}       → one example workflow's JSON
GET  /, /classic, /assets/*  → the dashboard and the V1 status page (spa.py)
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from flowforge import example_data, spa
from flowforge import state as app_state_module
from flowforge.api import connectors as connectors_api
from flowforge.api import flowmap as flowmap_api
from flowforge.api import runs as runs_api
from flowforge.api import stats as stats_api
from flowforge.connectors.registry import Registry, check_references, load_connectors_file
from flowforge.connectors.runtime import build_nodes  # noqa: F401 (re-exported for callers)
from flowforge.flowmap.planner import FixturePlanner
from flowforge.flowmap.service import FlowService
from flowforge.home import flowforge_home
from flowforge.security.logfilter import Redactor, install_log_redaction, secret_values_for
from flowforge.state import AppState, app_state
from flowforge.storage import Storage

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / "backend" / "workflows"
MCP_CHECK_TIMEOUT_S = runs_api.MCP_CHECK_TIMEOUT_S


def __getattr__(name: str) -> Any:
    """`main.state` stays readable for callers and tests written before api/ existed."""
    if name == "state":
        return app_state_module.current
    raise AttributeError(name)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    example = os.getenv("FLOWFORGE_EXAMPLE") == "1"
    redactor = Redactor()
    default_db = flowforge_home() / "example.db" if example else ROOT / "flowforge.db"
    if example:
        default_db.parent.mkdir(parents=True, exist_ok=True)
    storage = Storage(os.getenv("FLOWFORGE_DB") or default_db, redact=redactor.redact)
    registry = Registry(storage)
    registry.ensure_defaults()
    from_file = load_connectors_file(flowforge_home() / "connectors.json")
    for connector in from_file:
        registry.save(connector)
    connectors = registry.all()
    check_references(connectors)
    redactor.set_values(secret_values_for(connectors))
    restore_logging = install_log_redaction(redactor)
    storage.mark_interrupted()
    nodes, buckets = build_nodes(connectors)
    s = app_state_module.current = AppState(
        nodes=nodes, rate_limits=buckets, storage=storage, registry=registry, redactor=redactor,
        file_managed={c.id for c in from_file}, example=example)
    # the flow map (D17): only example mode has a Planner until Phase 5
    s.flows = FlowService(storage, lambda: {c.id: c for c in registry.all()}, FixturePlanner() if example else None)
    if example:  # offline nodes and a seeded history, never mixed with real data (D16)
        example_data.install(s)
        example_data.seed_flow(s)
        seeding = asyncio.create_task(example_data.seed(s))
        s.tasks.add(seeding)
        seeding.add_done_callback(s.tasks.discard)
    try:
        yield
    finally:
        s.shutting_down = True
        for task in list(s.tasks):
            task.cancel()
        if s.tasks:
            await asyncio.gather(*s.tasks, return_exceptions=True)
        for node in {id(n): n for n in [*s.nodes.values(), *s.retired_nodes]}.values():
            await node.aclose()
        restore_logging()


app = FastAPI(title="FlowForge", lifespan=lifespan)
app.include_router(runs_api.router)
app.include_router(connectors_api.router)
app.include_router(stats_api.router)
app.include_router(flowmap_api.router)


@app.get("/workflows")
def list_workflows() -> list[str]:
    names = {p.stem for p in WORKFLOWS_DIR.glob("*.json")}
    if app_state().example:
        names |= set(example_data.workflows())
    return sorted(names)


@app.get("/workflows/{name}")
def get_workflow(name: str) -> dict[str, Any]:
    if app_state().example and name in example_data.workflows():
        return example_data.workflows()[name]
    path = WORKFLOWS_DIR / f"{name}.json"
    if path.parent != WORKFLOWS_DIR or not path.exists():
        raise HTTPException(404, "unknown workflow")
    return json.loads(path.read_text(encoding="utf-8"))


spa.install(app)  # last: the built dashboard, /classic and the HTML-vs-JSON routing (D15)
