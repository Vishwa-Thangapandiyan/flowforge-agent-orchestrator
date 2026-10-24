"""Projects (D39): the home page's list, adding a folder, renaming and removing. A project's own pages are the usual
routes under `/p/<id>/`.

GET    /projects             {default, projects: [{id, name, path, added, opened, summary}], example: {id, name}}
POST   /projects             {path, name?} → the folder's project, added and mapped if new (201) or as it was (200)
PATCH  /projects/{id}        {name} → the project
POST   /projects/{id}/open   remember it was opened now (the home page's order)
DELETE /projects/{id}        remove FlowForge's copy (its map, checks, edits); the folder is never touched
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from flowforge import state as app_state_module
from flowforge.api.keys import from_this_machine
from flowforge.api.scan import REPO_SETTING
from flowforge.project_states import blank, close, ensure
from flowforge.projects import EXAMPLE_ID, Project, Projects
from flowforge.scan import ScanResult
from flowforge.security.keystore import KeyStore, report
from flowforge.storage import Storage

router = APIRouter()
EXAMPLE_NAME = "Example: trip planner"


class NewProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    name: str | None = None


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


def summary(storage: Storage, folder: Path) -> dict[str, int]:
    """A card's counts, from the saved map: dependencies, issues found, keys missing. Nothing is scanned."""
    saved = storage.latest_flow_version("deps", "accepted") or {}
    nodes = (saved.get("flow") or {}).get("nodes", [])
    scan = (saved.get("analysis") or {}).get("scan")
    out = {"dependencies": sum(1 for n in nodes if n.get("kind") != "start"), "issues": 0, "keys_missing": 0}
    if scan:
        try:
            result = ScanResult.model_validate(scan)
        except ValueError:
            return out
        out["issues"] = len(result.findings)
        keys = report(KeyStore(folder), result, verify=False)
        out["keys_missing"] = sum(1 for k in keys if k["status"] in ("missing", "unreadable"))
    return out


def card(p: Project) -> dict[str, Any]:
    folder = Path(p.path)
    open_state = app_state_module.projects.get(p.id)
    if open_state is not None:
        counts = summary(open_state.storage, folder)
    elif Path(p.db).is_file():
        counts = summary(Storage(Path(p.db)), folder)
    else:
        counts = {"dependencies": 0, "issues": 0, "keys_missing": 0}
    return {"id": p.id, "name": p.name, "path": p.path, "added": p.added, "opened": p.opened,
            "missing": not folder.is_dir(), "summary": counts}


@router.get("/projects")
def list_projects() -> dict[str, Any]:
    found = sorted(Projects().list(), key=lambda p: p.opened or p.added, reverse=True)
    return {"default": app_state_module.default_id, "projects": [card(p) for p in found],
            "example": {"id": EXAMPLE_ID, "name": EXAMPLE_NAME}}


@router.post("/projects", dependencies=[Depends(from_this_machine)])
async def add_project(body: NewProject, response: Response) -> dict[str, Any]:
    folder = Path(body.path).expanduser()
    if not folder.is_dir():
        raise HTTPException(422, "That isn't a folder on this machine.")
    folder = folder.resolve()
    registry = Projects()
    existing = registry.by_folder(folder)
    if existing is None:
        default = app_state_module.current
        if default is not None and default.storage.setting(REPO_SETTING) == str(folder):
            existing = registry.add(folder, db=default.storage.path)   # the default maps it already
        response.status_code = 201
    project = existing or registry.add(folder, name=body.name)
    if await ensure(project.id) is None:
        raise HTTPException(422, "That folder couldn't be opened.")
    return card(Projects().get(project.id) or project)


@router.patch("/projects/{project_id}", dependencies=[Depends(from_this_machine)])
def rename_project(project_id: str, body: Rename) -> dict[str, Any]:
    if not body.name.strip():
        raise HTTPException(422, "Give the project a name.")
    found = Projects().rename(project_id, body.name)
    if found is None:
        raise HTTPException(404, "No such project.")
    return card(found)


@router.post("/projects/{project_id}/open", dependencies=[Depends(from_this_machine)])
def opened(project_id: str) -> dict[str, Any]:
    if project_id != EXAMPLE_ID and Projects().get(project_id) is None:
        raise HTTPException(404, "No such project.")
    if project_id != EXAMPLE_ID:
        Projects().touch(project_id)
    return {"id": project_id, "opened": True}


@router.delete("/projects/{project_id}", dependencies=[Depends(from_this_machine)])
async def remove_project(project_id: str) -> dict[str, Any]:
    """FlowForge's copy goes (its database); the folder and your code are never touched (D39)."""
    if project_id == EXAMPLE_ID:
        raise HTTPException(409, "The example is built in.")
    found = Projects().get(project_id)
    if found is None:
        raise HTTPException(404, "No such project.")
    if project_id == app_state_module.default_id:   # hand over to the next project opened, else to a blank FlowForge
        rest = [p for p in Projects().list() if p.id != project_id and Path(p.path).is_dir()]
        nxt = max(rest, key=lambda p: p.opened or p.added, default=None)
        handed = await ensure(nxt.id) if nxt else None
        old = app_state_module.current
        app_state_module.current = handed or (blank(old) if old is not None else None)
        app_state_module.default_id = nxt.id if handed else None
    Projects().remove(project_id)
    state = app_state_module.projects.pop(project_id, None)
    if state is not None:
        await close(state)
        state.storage.conn.close()
    for suffix in ("", "-wal", "-shm"):
        Path(found.db + suffix).unlink(missing_ok=True)
    return {"id": project_id, "removed": True}
