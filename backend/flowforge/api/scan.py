"""Choose the folder whose dependency map you see (D21). One repo per database in V1.

GET  /scan                       the folder, whether this is example mode, and a summary of the last scan
POST /scan {path, replace?}      scan a folder and draw its map; a different folder needs replace (a fresh map)

Re-scanning the same folder is POST /flow/recheck: a new version and a diff, never an overwrite (D17).
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from flowforge.flowmap.planner import ScanPlanner
from flowforge.state import AppState, app_state
from flowforge.storage import Storage

REPO_SETTING = "repo_path"
EXAMPLE_REPO = Path(__file__).resolve().parents[3] / "examples" / "trip-planner"   # scanned live in example mode

router = APIRouter()


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)
    replace: bool = False


def startup_repo(storage: Storage, example: bool) -> Path | None:
    """The folder to map at start-up: the sample app in example mode; else FLOWFORGE_REPO (`flowforge --repo`),
    which starts a fresh map when it names a different folder; else the folder chosen last time."""
    if example:
        return EXAMPLE_REPO
    chosen = os.getenv("FLOWFORGE_REPO")
    if chosen and Path(chosen).expanduser().is_dir():
        path = str(Path(chosen).expanduser().resolve())
        if storage.setting(REPO_SETTING) != path:
            storage.flows("deps").clear()
            storage.set_setting(REPO_SETTING, path)
    saved = storage.setting(REPO_SETTING)
    return Path(saved) if saved else None


def repo_path(s: AppState) -> Path | None:
    if s.example:
        return EXAMPLE_REPO
    saved = s.storage.setting(REPO_SETTING)
    return Path(saved) if saved else None


@router.get("/scan")
def get_scan() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    analysis = s.flows["deps"].analysis() if "deps" in s.flows else None
    summary = None
    if analysis and analysis.get("scan"):
        deps = analysis["scan"]["dependencies"]
        summary = {"files": analysis["scan"]["files_scanned"], "dependencies": len(deps),
                   "unconfirmed": sum(d["status"] == "unconfirmed" for d in deps),
                   "kinds": dict(Counter(d["kind"] for d in deps))}
    return {"repo": str(repo) if repo else None, "name": repo.name if repo else None, "example": s.example,
            "summary": summary}


@router.post("/scan", status_code=201)
def post_scan(body: ScanRequest) -> dict[str, Any]:
    """Read-only and offline (D20): the folder is read, never run, and nothing is sent anywhere."""
    s = app_state()
    if s.example:
        raise HTTPException(409, "Example mode always maps the sample app. Run FlowForge without --example "
                                 "to scan your own folder.")
    path = Path(body.path).expanduser()
    if not path.is_dir():
        raise HTTPException(422, "that isn't a folder on this machine")
    path = path.resolve()
    service = s.flows["deps"]
    current = s.storage.setting(REPO_SETTING)
    if current != str(path):
        if current and service.store.count_flow_versions() and not body.replace:
            raise HTTPException(409, f"there is already a map of {Path(current).name}; scanning {path.name} "
                                     "starts a fresh map (send replace: true)")
        service.store.clear()   # a different repo: its own versions, edits and positions from scratch
        s.storage.set_setting(REPO_SETTING, str(path))
    service.planner = ScanPlanner(path)
    service.first_map()         # nothing to do when this folder already has a map
    return {"repo": str(path), "name": path.name, "version": service.current().get("version")}
