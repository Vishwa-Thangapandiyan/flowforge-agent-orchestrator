"""Keys the coding agent never sees (D36): their statuses for the map, and the dashboard's write-only box.

GET    /keys          {repo, example, summary: {missing, env_file}, keys: [{name, status, ref, deps, command}]}
PUT    /keys/{name}   {"value": "..."} → {name, status: "saved"}; the value is never sent back
DELETE /keys/{name}   → {name, removed}
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from flowforge.api.scan import repo_path
from flowforge.scan import ScanResult
from flowforge.scan import scan as scan_repo
from flowforge.security.keystore import BadKey, KeyStore, report
from flowforge.state import AppState, app_state

router = APIRouter()


class KeyValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


def learn_saved_keys(s: AppState, repo: Path | None) -> None:
    """The redactor masks every value saved for this folder from now on, wherever it would show (D36)."""
    if repo is None or s.example:
        return
    try:
        s.redactor.learn(KeyStore(repo).env().values())
    except Exception:   # a keychain that can't be read must not stop FlowForge
        pass


def _scan(s: AppState, repo: Path) -> ScanResult:
    """The map's stored scan, so a re-scan updates the keys; the folder read again if none is stored."""
    analysis = s.flows["deps"].analysis() if "deps" in s.flows else None
    stored = (analysis or {}).get("scan")
    if stored:
        try:
            return ScanResult.model_validate(stored)
        except ValueError:
            pass
    return scan_repo(repo)


def _writable(s: AppState) -> Path:
    repo = repo_path(s)
    if s.example:
        raise HTTPException(409, "Example data: keys aren't saved. Map your own folder to add keys.")
    if repo is None:
        raise HTTPException(409, "Map a folder first: keys belong to one folder.")
    return repo


@router.get("/keys")
def keys() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    if repo is None or not repo.is_dir():
        return {"repo": None, "example": s.example, "summary": {}, "keys": []}
    found = report(KeyStore(repo), _scan(s, repo))
    summary = Counter(k["status"] for k in found if k["status"] != "saved")
    return {"repo": repo.name, "example": s.example, "summary": dict(summary), "keys": found}


@router.put("/keys/{name}")
def save_key(name: str, body: KeyValue) -> dict[str, Any]:
    s = app_state()
    repo = _writable(s)
    try:
        KeyStore(repo).add(name, body.value)
    except BadKey as e:
        raise HTTPException(400, str(e)) from None
    s.redactor.learn([body.value.strip()])
    return {"name": name, "status": "saved"}


@router.delete("/keys/{name}")
def remove_key(name: str) -> dict[str, Any]:
    repo = _writable(app_state())
    return {"name": name, "removed": KeyStore(repo).remove(name)}
