"""Keys the coding agent never sees (D36): their statuses for the map, and the dashboard's write-only box.

GET    /keys          {repo, example, summary: {missing, env_file}, keys: [{name, status, ref, deps, command}]}
PUT    /keys/{name}          {"value": "..."} → {name, status: "saved"}; the value is never sent back
POST   /keys/{name}/import   the value of `name` in the folder's .env, saved (D37) → {name, status: "saved"}
DELETE /keys/{name}          → {name, removed}
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from flowforge.api.scan import repo_path
from flowforge.home import command_line
from flowforge.scan import ScanResult
from flowforge.scan import scan as scan_repo
from flowforge.security.keystore import BadKey, KeyStore, report
from flowforge.state import AppState, app_state
from flowforge.storage import Storage, now_iso

router = APIRouter()

KEY_REQUESTS_SETTING = "key_requests"   # [{repo, name, why, at}]: keys your agent asked for (D38), never a value


def key_requests(storage: Storage, repo: Path) -> list[dict[str, Any]]:
    """`repo`'s open requests, oldest first."""
    try:
        found = json.loads(storage.setting(KEY_REQUESTS_SETTING) or "[]")
    except ValueError:
        return []
    here = str(repo.resolve())
    return [r for r in found if isinstance(r, dict) and r.get("repo") == here] if isinstance(found, list) else []


def _all_requests(storage: Storage) -> list[dict[str, Any]]:
    try:
        found = json.loads(storage.setting(KEY_REQUESTS_SETTING) or "[]")
    except ValueError:
        return []
    return [r for r in found if isinstance(r, dict) and r.get("repo")] if isinstance(found, list) else []


def add_key_request(storage: Storage, repo: Path, name: str, why: str) -> None:
    here = str(repo.resolve())
    kept = [r for r in _all_requests(storage) if (r["repo"], r.get("name")) != (here, name)]
    kept.append({"repo": here, "name": name, "why": why[:200], "at": now_iso()})
    storage.set_setting(KEY_REQUESTS_SETTING, json.dumps(kept))


def clear_key_requests(storage: Storage, repo: Path, names: Iterable[str]) -> None:
    """A request ends once its key is saved."""
    here, done = str(repo.resolve()), set(names)
    found = _all_requests(storage)
    kept = [r for r in found if not (r["repo"] == here and r.get("name") in done)]
    if len(kept) != len(found):
        storage.set_setting(KEY_REQUESTS_SETTING, json.dumps(kept))


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


def _loopback_peer(address: str | None) -> bool:
    """The connection itself comes from this machine (127.0.0.0/8 or ::1)."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(address or "")
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)   # ::ffff:127.0.0.1 on a dual-stack socket
    return (mapped or ip).is_loopback


def from_this_machine(request: Request) -> None:
    """Saving a key, a fix, the lock and the key view need the dashboard on this machine (D36, D37). The caller's real
    address must be this machine (with --host 0.0.0.0 another machine could fake the headers: Codex review), and
    Host and Origin must name it too, so a web page can't reach it through DNS rebinding or from another site."""
    host = urlsplit(f"//{request.headers.get('host', '')}").hostname
    origin = request.headers.get("origin")
    peer = request.client.host if request.client else None
    if (not _loopback_peer(peer) or host not in _LOOPBACK
            or (origin is not None and urlsplit(origin).hostname not in _LOOPBACK)):
        raise HTTPException(403, "This works only from the dashboard on this machine (open it at localhost).")


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
    store = KeyStore(repo)
    asked = key_requests(s.storage, repo)
    clear_key_requests(s.storage, repo, [n for n in store.names() if any(r["name"] == n for r in asked)])
    asked = [r for r in asked if r["name"] not in set(store.names())]
    found = report(store, stored_scan(s, repo), also=[r["name"] for r in asked])
    for k in found:
        k["requested"] = any(r["name"] == k["name"] for r in asked)
    summary = Counter(k["status"] for k in found if k["status"] != "saved")
    return {"repo": repo.name, "example": s.example, "summary": dict(summary), "keys": found,
            "requests": [{"name": r["name"], "why": r["why"], "at": r["at"]} for r in asked],
            "run": command_line("run", "--repo", str(repo), "--")}   # + how you start your app


@router.put("/keys/{name}", dependencies=[Depends(from_this_machine)])
def save_key(name: str, body: KeyValue) -> dict[str, Any]:
    s = app_state()
    repo = _writable(s)
    try:
        KeyStore(repo).add(name, body.value)
    except BadKey as e:
        raise HTTPException(400, str(e)) from None
    s.redactor.learn([body.value.strip()])
    clear_key_requests(s.storage, repo, [name])
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
    clear_key_requests(s.storage, repo, [name])
    return {"name": name, "status": "saved"}


@router.delete("/keys/{name}", dependencies=[Depends(from_this_machine)])
def remove_key(name: str) -> dict[str, Any]:
    repo = _writable(app_state())
    return {"name": name, "removed": KeyStore(repo).remove(name)}
