"""Keys the coding agent never sees (D36): their statuses for the map, and the dashboard's write-only box.

GET    /keys          {repo, example, summary: {missing, env_file}, keys: [{name, status, ref, deps, command}]}
PUT    /keys/{name}          {"value": "..."} → {name, status: "saved"}; the value is never sent back
POST   /keys/{name}/import   the value of `name` in the folder's .env, saved (D37) → {name, status: "saved"}
DELETE /keys/{name}          → {name, removed}
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
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
    if repo is None:
        return
    try:
        s.redactor.learn(KeyStore(repo).env().values())
    except Exception:   # a keychain that can't be read must not stop FlowForge
        pass


def stored_scan(s: AppState, repo: Path) -> ScanResult:
    """The map's stored scan, so a re-scan updates the keys; the folder read again if none is stored."""
    analysis = s.flows["deps"].analysis() if "deps" in s.flows else None
    stored = (analysis or {}).get("scan")
    if stored:
        try:
            return ScanResult.model_validate(stored)
        except ValueError:
            pass
    return scan_repo(repo)


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _this_machine(name: str | None) -> bool:
    chosen = os.getenv("FLOWFORGE_HOST", "")
    return bool(name) and (name in _LOOPBACK or (name == chosen and chosen not in ("0.0.0.0", "::")))


def from_this_machine(request: Request) -> None:
    """Saving or forgetting a key needs the dashboard's own address (D36). A web page can't do it: through DNS
    rebinding its Host is its own name, and from another site its Origin is."""
    host = urlsplit(f"//{request.headers.get('host', '')}").hostname
    origin = request.headers.get("origin")
    if not _this_machine(host) or (origin is not None and not _this_machine(urlsplit(origin).hostname)):
        raise HTTPException(403, "Keys can only be saved from the dashboard on this machine.")


def _writable(s: AppState) -> Path:
    """The folder keys are saved for. Example data saves too (D37): its keys belong to the example's folder."""
    repo = repo_path(s)
    if repo is None:
        raise HTTPException(409, "Map a folder first: keys belong to one folder.")
    return repo


@router.get("/keys")
def keys() -> dict[str, Any]:
    s = app_state()
    repo = repo_path(s)
    if repo is None or not repo.is_dir():
        return {"repo": None, "example": s.example, "summary": {}, "keys": []}
    found = report(KeyStore(repo), stored_scan(s, repo))
    summary = Counter(k["status"] for k in found if k["status"] != "saved")
    return {"repo": repo.name, "example": s.example, "summary": dict(summary), "keys": found}


@router.put("/keys/{name}", dependencies=[Depends(from_this_machine)])
def save_key(name: str, body: KeyValue) -> dict[str, Any]:
    s = app_state()
    repo = _writable(s)
    try:
        KeyStore(repo).add(name, body.value)
    except BadKey as e:
        raise HTTPException(400, str(e)) from None
    s.redactor.learn([body.value.strip()])
    return {"name": name, "status": "saved"}


@router.post("/keys/{name}/import", dependencies=[Depends(from_this_machine)])
def import_key(name: str) -> dict[str, Any]:
    """Move one key in from .env: the server reads that value from the file, so nothing is copied by hand (D37)."""
    from dotenv import dotenv_values

    s = app_state()
    repo = _writable(s)
    value = dotenv_values(repo / ".env").get(name) if (repo / ".env").is_file() else None
    if not value or not value.strip():
        raise HTTPException(404, f"{name} isn't set in .env.")
    try:
        KeyStore(repo).add(name, value)
    except BadKey as e:
        raise HTTPException(400, str(e)) from None
    s.redactor.learn([value.strip()])
    return {"name": name, "status": "saved"}


@router.delete("/keys/{name}", dependencies=[Depends(from_this_machine)])
def remove_key(name: str) -> dict[str, Any]:
    repo = _writable(app_state())
    return {"name": name, "removed": KeyStore(repo).remove(name)}
