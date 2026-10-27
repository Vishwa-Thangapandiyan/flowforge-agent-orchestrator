"""Keys the coding agent never sees (D36): their statuses for the map, and the dashboard's write-only box.

GET    /keys          {repo, example, summary: {missing, env_file}, keys: [{name, status, ref, deps, command}]}
PUT    /keys/{name}          {"value": "..."} → {name, status: "saved"}; the value is never sent back
POST   /keys/{name}/import   the value of `name` in the folder's .env, saved (D37) → {name, status: "saved"}
POST   /keys/{name}/add-to-code   {value, ref, check}: the key into the app at its spot (D44) → {name, ref, changed}
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
from flowforge.scan import ScanResult
from flowforge.scan import scan as scan_repo
from flowforge.security.keystore import BadKey, KeyStore, report
from flowforge.security.wire import DEFINES, CantAdd, Spot, add_to_code, key_spots
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


class AddToCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    check: str
    value: str | None = None   # none: the saved value, or for a key written in the open, the code's


_FIRST = {"open": 0, "placeholder": 1, "reads": 2, "setting": 3}


def _spots(repo: Path) -> dict[str, Spot]:
    """Each key's or setting's spot (D44, D45): an open key first, then a placeholder, then a line that reads it."""
    out: dict[str, Spot] = {}
    for spot in sorted(key_spots(repo), key=lambda sp: (_FIRST[sp.kind], sp.path, sp.line)):
        out.setdefault(spot.name, spot)
    return out


def _settings(repo: Path, spots: dict[str, Spot], saved: dict[str, str]) -> list[dict[str, Any]]:
    """The settings the keys need (D45): where each goes, whether the app has it, and a suggested value."""
    from flowforge.security.wire import setting_problem, suggest

    given = _given(repo, {sp.sink for sp in spots.values() if sp.sink and sp.sink != "dart-defines"})
    out = []
    for name, spot in sorted(spots.items()):
        if spot.kind != "setting":
            continue
        value = given.get(name) or ""
        has = bool(value) and setting_problem(name, value) is None   # a key in the URL's place isn't "in your app"
        out.append({**spot.public(), "in_app": has, "suggestion": None if has else suggest(name, saved)})
    return out


def _given(repo: Path, env_files: set[str]) -> dict[str, str]:
    """Every value the app is given in its key files (`.flowforge/dart-defines.json`, `.env`, `.env.local`, others
    the code loads). Stays in this module: callers keep names only."""
    from dotenv import dotenv_values

    found: dict[str, str] = {}
    try:
        defines = json.loads((repo / DEFINES).read_text()) if (repo / DEFINES).is_file() else {}
        found |= {k: v for k, v in defines.items() if isinstance(v, str)} if isinstance(defines, dict) else {}
    except (OSError, ValueError):
        pass
    for env in sorted({".env", ".env.local", *env_files}):
        if (repo / env).is_file() and (repo / env).resolve().is_relative_to(repo.resolve()):
            found |= {k: v for k, v in dotenv_values(repo / env).items() if v}
    return found


def _in_app(repo: Path, saved: dict[str, str], env_files: set[str]) -> set[str]:
    """Saved keys whose value is already in a file the app reads: the same value, so `NAME=` or an old one isn't
    "in your app" (Codex review). Values are compared here and dropped; only names leave."""
    found = _given(repo, env_files)
    return {name for name, value in saved.items() if found.get(name) == value}


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


@router.get("/keys/asked")
def keys_asked() -> dict[str, list[str]]:
    """The names your agent asked for and you haven't saved yet (D38): cheap enough for the rail's badge to poll,
    since it never reads the code. Names only."""
    s = app_state()
    repo = repo_path(s)
    if repo is None or not repo.is_dir():
        return {"names": []}
    saved = set(KeyStore(repo).names())
    return {"names": [r["name"] for r in key_requests(s.storage, repo) if r["name"] not in saved]}


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
    every = _spots(repo)
    spots = {n: sp for n, sp in every.items() if sp.kind != "setting"}
    found = report(store, stored_scan(s, repo), also=[*(r["name"] for r in asked), *spots])
    env_files = {sp.sink for sp in spots.values() if sp.sink and sp.sink != "dart-defines"}
    in_app = _in_app(repo, store.env(), env_files) if store.names() else set()
    for k in found:
        k["requested"] = any(r["name"] == k["name"] for r in asked)
        spot = spots.get(str(k["name"]))
        k["spot"] = spot.public() if spot else None   # where "Add to code" puts it (D44)
        k["in_app"] = k["name"] in in_app
        if spot and not k["ref"]:
            k["ref"] = spot.ref
    summary = Counter(k["status"] for k in found if k["status"] != "saved")
    saved = store.env() if any(sp.kind == "setting" for sp in every.values()) and store.names() else {}
    return {"repo": repo.name, "example": s.example, "summary": dict(summary), "keys": found,
            "settings": _settings(repo, every, saved),
            "requests": [{"name": r["name"], "why": r["why"], "at": r["at"]} for r in asked]}


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


@router.post("/keys/{name}/add-to-code", dependencies=[Depends(from_this_machine)])
def add_key_to_code(name: str, body: AddToCode) -> dict[str, Any]:
    """The box's one click (D44): the Vault, the code's read and the file the app reads, never a value back."""
    s = app_state()
    if s.example:
        raise HTTPException(409, "The example's code isn't changed. Open your own project to add keys to code.")
    repo = _writable(s)
    value = body.value
    if value is None:   # saved before, so nothing to retype (an open key's value comes from the code instead)
        value = KeyStore(repo).env().get(name)
    try:
        done = add_to_code(repo, name, body.ref, body.check, value)
    except CantAdd as e:
        raise HTTPException(409, str(e)) from None
    saved = KeyStore(repo).env().get(str(done["name"]))
    if saved:
        s.redactor.learn([saved])
    clear_key_requests(s.storage, repo, [str(done["name"])])
    return done


@router.delete("/keys/{name}", dependencies=[Depends(from_this_machine)])
def remove_key(name: str) -> dict[str, Any]:
    repo = _writable(app_state())
    return {"name": name, "removed": KeyStore(repo).remove(name)}
