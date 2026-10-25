"""FastAPI app: start-up wiring and small routes. Runs: api/runs.py. Connectors: api/connectors.py.

GET  /workflows              → names of the example workflows
GET  /workflows/{name}       → one example workflow's JSON
GET  /, /classic, /assets/*  → the dashboard and the V1 status page (spa.py)
"""

from __future__ import annotations

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
from flowforge.api import agent as agent_api
from flowforge.api import apps as apps_api
from flowforge.api import checks as checks_api
from flowforge.api import connectors as connectors_api
from flowforge.api import flowmap as flowmap_api
from flowforge.api import issues as issues_api
from flowforge.api import keys as keys_api
from flowforge.api import lock as lock_api
from flowforge.api import projects as projects_api
from flowforge.api import runs as runs_api
from flowforge.api import scan as scan_api
from flowforge.api import security as security_api
from flowforge.api import settings as settings_api
from flowforge.api import stats as stats_api
from flowforge.connectors.registry import load_connectors_file
from flowforge.connectors.runtime import build_nodes  # noqa: F401 (re-exported for callers)
from flowforge.home import database_path, flowforge_home, resource
from flowforge.project_states import build_state, point_at_example
from flowforge.project_states import close as close_state
from flowforge.project_states import ensure as ensure_project
from flowforge.projects import EXAMPLE_ID, Projects, valid_id
from flowforge.security.local_only import LocalOnly
from flowforge.security.logfilter import Redactor, install_log_redaction
from flowforge.state import app_state
from flowforge.storage import Storage

load_dotenv()

WORKFLOWS_DIR = resource("workflows")   # inside the package when installed (D34)
MCP_CHECK_TIMEOUT_S = runs_api.MCP_CHECK_TIMEOUT_S


def __getattr__(name: str) -> Any:
    """`main.state` stays readable for callers and tests written before api/ existed."""
    if name == "state":
        return app_state_module.current
    raise AttributeError(name)


def _default_db(example: bool) -> Path:
    """The default project's database: FLOWFORGE_DB; else, for `--repo PATH`, that folder's project (an older
    database that maps it, or no folder yet, stays as it is: D39); else the project opened last; else the usual one."""
    if os.getenv("FLOWFORGE_DB") or example:
        return database_path(example)
    projects = Projects()
    chosen = os.getenv("FLOWFORGE_REPO")
    legacy = database_path()
    if chosen:
        found = projects.by_folder(Path(chosen))
        if found:
            return Path(found.db)
        older = Storage(legacy).setting(scan_api.REPO_SETTING) if legacy.is_file() else None
        if older in (None, str(Path(chosen).expanduser().resolve())):
            return legacy
        return Path(projects.add(Path(chosen)).db)   # another folder: a project of its own, not a fresh map
    last = max((p for p in projects.list() if Path(p.path).is_dir()), key=lambda p: p.opened or p.added, default=None)
    return Path(last.db) if last else legacy


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    example = os.getenv("FLOWFORGE_EXAMPLE") == "1"
    redactor = Redactor()
    if example:
        flowforge_home().mkdir(parents=True, exist_ok=True)
    from_file = load_connectors_file(flowforge_home() / "connectors.json")
    s = build_state(_default_db(example), redactor, from_file, example, first=True)
    restore_logging = install_log_redaction(redactor)
    app_state_module.current = s
    app_state_module.projects = {}
    app_state_module.default_id = None
    if example:
        point_at_example(s)
        app_state_module.projects[EXAMPLE_ID] = s
        app_state_module.default_id = EXAMPLE_ID
    else:   # your folder: from --repo or the last one chosen, mapped now if it has no maps yet
        keys_api.learn_saved_keys(s, Path(os.environ["FLOWFORGE_REPO"]) if os.getenv("FLOWFORGE_REPO")
                                  else scan_api.repo_path(s))
        scan_api.startup_repo(s.storage, s.flows)
        repo = scan_api.repo_path(s)
        if repo is not None:   # the folder it maps is a project: listed, and the default (D39)
            project = Projects().add(repo, db=s.storage.path)
            app_state_module.projects[project.id] = s
            app_state_module.default_id = project.id
            Projects().touch(project.id)
    apps_api.started()   # server.json: where the agent's MCP server finds FlowForge (D43)
    try:
        yield
    finally:
        apps_api.stopping()
        for each in {id(x): x for x in [s, *app_state_module.projects.values()]}.values():
            await close_state(each)
        restore_logging()


class ProjectPrefix:
    """`/p/<id>/rest` → `/rest` for project <id> (D39): routes stay as they are; `app_state()` follows the prefix."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and not apps_api.registered() and (scope.get("server") or (None, None))[1]:
            apps_api.register(int(scope["server"][1]))   # started without the port known: tell the agent (D43)
        path = scope.get("path", "") if scope["type"] in ("http", "websocket") else ""
        if not path.startswith("/p/"):
            await self.app(scope, receive, send)
            return
        pid, _, rest = path[3:].partition("/")
        state = await ensure_project(pid) if valid_id(pid) else None
        if state is None:
            if scope["type"] == "http":
                body = json.dumps({"detail": "No such project."}).encode()
                await send({"type": "http.response.start", "status": 404,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
            return
        token = app_state_module.project_var.set(pid)
        try:
            inner = "/" + rest
            await self.app({**scope, "path": inner, "raw_path": inner.encode()}, receive, send)
        finally:
            app_state_module.project_var.reset(token)


app = FastAPI(title="FlowForge", lifespan=lifespan)
app.add_middleware(ProjectPrefix)
app.add_middleware(LocalOnly)   # added last, so it runs first: nothing answers another machine or site (D47)
app.include_router(runs_api.router)
app.include_router(connectors_api.router)
app.include_router(stats_api.router)
app.include_router(flowmap_api.router)
app.include_router(scan_api.router)
app.include_router(checks_api.router)
app.include_router(agent_api.router)
app.include_router(security_api.router)
app.include_router(keys_api.router)
app.include_router(issues_api.router)
app.include_router(lock_api.router)
app.include_router(projects_api.router)
app.include_router(settings_api.router)
app.include_router(apps_api.router)


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
