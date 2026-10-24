"""One project's state, built the way start-up always built it (D39): its storage, connectors, nodes and maps, pointed
at its folder. The default project is built at start-up; any other the first time a `/p/<id>/` request names it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from flowforge import example_data
from flowforge import state as app_state_module
from flowforge.api import keys as keys_api
from flowforge.api import scan as scan_api
from flowforge.connectors.models import Connector
from flowforge.connectors.registry import Registry, check_references
from flowforge.connectors.runtime import build_nodes
from flowforge.flowmap.planner import CodeFlowPlanner, ScanPlanner
from flowforge.flowmap.service import FlowService
from flowforge.home import flowforge_home
from flowforge.projects import EXAMPLE_ID, Projects
from flowforge.security.logfilter import Redactor, secret_values_for
from flowforge.state import AppState
from flowforge.storage import Storage

_building: dict[str, asyncio.Lock] = {}


def build_state(db: Path, redactor: Redactor, from_file: list[Connector], example: bool,
                first: bool = False) -> AppState:
    """Storage, connectors, nodes and the two maps (D17, D21, D25), not yet pointed at a folder. `first`: the
    process's first project, whose connectors set the redactor's values; later ones only add theirs."""
    storage = Storage(db, redact=redactor.redact)
    registry = Registry(storage)
    registry.ensure_defaults()
    for connector in from_file:
        registry.save(connector)
    connectors = registry.all()
    check_references(connectors)
    if first:
        redactor.set_values(secret_values_for(connectors))
    else:
        redactor.learn(secret_values_for(connectors))
    storage.mark_interrupted()
    nodes, buckets = build_nodes(connectors)
    s = AppState(nodes=nodes, rate_limits=buckets, storage=storage, registry=registry, redactor=redactor,
                 file_managed={c.id for c in from_file}, example=example)

    def connected() -> dict[str, Connector]:
        return {c.id: c for c in registry.all()}

    drawn = storage.flows("flow").latest_flow_version("accepted")
    if example and drawn and (drawn["flow"] or {}).get("source") != "code":
        storage.clear_map("flow")   # an example.db from before D25 still holds a hand-drawn flow
    s.flows = {"deps": FlowService(storage.flows("deps"), connected, None),
               "flow": FlowService(storage.flows("flow"), connected, None)}
    return s


def point_at_example(s: AppState) -> None:
    """Example data (D16, D23): the shipped trip planner, offline nodes and a seeded history, never mixed with yours.
    Needs a running event loop (the history is seeded in the background)."""
    s.flows["deps"].planner = ScanPlanner(scan_api.EXAMPLE_REPO)
    s.flows["flow"].planner = CodeFlowPlanner(scan_api.EXAMPLE_REPO, lambda: example_data.latencies(s.storage))
    keys_api.learn_saved_keys(s, scan_api.EXAMPLE_REPO)   # example data saves keys too (D37)
    example_data.install(s)
    example_data.seed_flow(s)
    seeding = asyncio.create_task(example_data.seed(s))
    s.tasks.add(seeding)
    seeding.add_done_callback(s.tasks.discard)


def point_at_folder(s: AppState, folder: Path) -> None:
    """A project's folder: its saved keys masked, its maps drawn now if it has none (plain code, D20)."""
    keys_api.learn_saved_keys(s, folder)
    scan_api.choose_repo(s.storage, s.flows, folder, replace=False)


async def ensure(project_id: str) -> AppState | None:
    """The project's state, built the first time it is asked for; None when there is no such project."""
    found = app_state_module.projects.get(project_id)
    if found is not None:
        return found
    lock = _building.setdefault(project_id, asyncio.Lock())
    async with lock:
        found = app_state_module.projects.get(project_id)
        if found is not None:
            return found
        default = app_state_module.current
        if default is None:
            return None
        redactor, from_file = default.redactor, [default.registry.get(i) for i in sorted(default.file_managed)]
        from_file = [c for c in from_file if c is not None]
        if project_id == EXAMPLE_ID:
            s = build_state(flowforge_home() / "example.db", redactor, from_file, example=True)
            point_at_example(s)
        else:
            project = Projects().get(project_id)
            if project is None or not Path(project.path).is_dir():
                return None
            s = build_state(Path(project.db), redactor, from_file, example=False)
            await run_in_threadpool(point_at_folder, s, Path(project.path))   # a first scan can take a moment
            Projects().touch(project_id)
        app_state_module.projects[project_id] = s
        return s


async def close(s: AppState) -> None:
    """Stop a project's background work and close its nodes."""
    s.shutting_down = True
    for task in list(s.tasks):
        task.cancel()
    if s.tasks:
        await asyncio.gather(*s.tasks, return_exceptions=True)
    for node in {id(n): n for n in [*s.nodes.values(), *s.retired_nodes]}.values():
        await node.aclose()
