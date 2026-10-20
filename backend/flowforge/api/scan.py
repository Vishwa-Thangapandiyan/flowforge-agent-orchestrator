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
from flowforge.flowmap.service import FlowService
from flowforge.state import AppState, app_state
from flowforge.storage import Storage

REPO_SETTING = "repo_path"
EXAMPLE_REPO = Path(__file__).resolve().parents[3] / "examples" / "trip-planner"   # scanned live in example mode

router = APIRouter()


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)
    replace: bool = False


class RepoChangeError(ValueError):
    """A different folder while a map exists: it needs an explicit replace (D21)."""


def choose_repo(storage: Storage, service: FlowService, path: Path, replace: bool) -> None:
    """Map `path`: the same folder keeps its map; a different one starts a fresh map, but only with `replace`."""
    current = storage.setting(REPO_SETTING)
    changed = current != str(path)
    if changed and current and service.has_map() and not replace:
        raise RepoChangeError(f"there is already a map of {Path(current).name}; mapping {path.name} starts a fresh map")
    if changed:
        storage.set_setting(REPO_SETTING, str(path))
    service.map_folder(ScanPlanner(path), fresh=changed)


def startup_repo(storage: Storage, service: FlowService) -> None:
    """At start-up outside example mode: FLOWFORGE_REPO (`flowforge --repo`), else the folder chosen last time.
    A different folder needs FLOWFORGE_REPO_REPLACE=1 (`--replace`); otherwise FlowForge refuses to start."""
    chosen = os.getenv("FLOWFORGE_REPO")
    if chosen:
        path = Path(chosen).expanduser()
        if not path.is_dir():
            raise RuntimeError(f"FLOWFORGE_REPO={chosen} is not a folder")
        try:
            choose_repo(storage, service, path.resolve(), replace=os.getenv("FLOWFORGE_REPO_REPLACE") == "1")
        except RepoChangeError as err:
            raise RuntimeError(f"{err}. Run with --replace to start it fresh.") from None
        return
    saved = storage.setting(REPO_SETTING)
    if saved and Path(saved).is_dir():
        service.map_folder(ScanPlanner(Path(saved)), fresh=False)


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
    try:
        choose_repo(s.storage, service, path, body.replace)
    except RepoChangeError as err:
        raise HTTPException(409, f"{err} (send replace: true)") from None
    return {"repo": str(path), "name": path.name, "version": service.current().get("version")}
