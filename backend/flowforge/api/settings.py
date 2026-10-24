"""Settings (D40): what applies to every project. Nothing here is secret, so there is no login; every change answers
only to the dashboard on this machine (D36), and the lock and key view stay behind the Vault (D37).

GET    /settings                 {welcome_done, map_style, version, install, home, total_bytes, projects, agent, vault}
PATCH  /settings                 {welcome_done?, map_style?} → the settings
DELETE /projects/{id}/checks     a project's check history goes; its yeses stay
DELETE /projects/{id}/confirmed  a project's yes to start its MCP servers is taken back
POST   /settings/update-check    one GET to pypi.org, only when pressed → {current, latest, newer}
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from flowforge import home
from flowforge import settings as settings_file
from flowforge import state as app_state_module
from flowforge.agent import AGENT_CALLS_SETTING
from flowforge.api.agent import agents_for, server_command
from flowforge.api.checks import CONFIRMED_SETTING
from flowforge.api.keys import from_this_machine
from flowforge.projects import Project, Projects
from flowforge.security.keystore import _keychain_works
from flowforge.security.lock import Lock
from flowforge.storage import Storage

router = APIRouter()

PYPI_URL = f"https://pypi.org/pypi/{home.DIST_NAME}/json"
UPDATE_TRANSPORT: httpx.BaseTransport | None = None   # tests stub it: no test reaches pypi.org


@contextmanager
def _storage(p: Project) -> Iterator[Storage | None]:
    """A project's database: its open state's, else opened for this request and closed after."""
    state = app_state_module.projects.get(p.id)
    if state is not None:
        yield state.storage
        return
    if not Path(p.db).is_file():
        yield None
        return
    storage = Storage(Path(p.db))
    try:
        yield storage
    finally:
        storage.conn.close()


def _size(db: str) -> int:
    return sum(Path(db + suffix).stat().st_size for suffix in ("", "-wal") if Path(db + suffix).is_file())


def _json_list(text: str | None) -> list[Any]:
    try:
        found = json.loads(text or "[]")
    except ValueError:
        return []
    return found if isinstance(found, list) else []


def _project_row(p: Project) -> tuple[dict[str, Any], dict[str, Any] | None]:
    with _storage(p) as storage:
        confirmed = sorted(_json_list(storage.setting(CONFIRMED_SETTING))) if storage else []
        checks = storage.count_checks() if storage else 0
        calls = _json_list(storage.setting(AGENT_CALLS_SETTING)) if storage else []
    row = {"id": p.id, "name": p.name, "path": p.path, "size_bytes": _size(p.db), "confirmed": confirmed,
           "checks": checks}
    last = calls[0] if calls and isinstance(calls[0], dict) else None
    return row, last


def _agent(last_calls: list[dict[str, Any]]) -> dict[str, Any]:
    env = {"FLOWFORGE_HOME": str(home.flowforge_home())} if os.getenv("FLOWFORGE_HOME") else {}
    newest = max(last_calls, key=lambda c: str(c.get("at", "")), default=None)
    command = server_command(None, None)
    return {"connected": newest is not None, "last_call": newest, "command": command,
            "agents": agents_for(command, env)}


def _settings_data() -> dict[str, Any]:
    rows, last_calls, outside = [], [], 0
    folder = home.flowforge_home()
    for p in Projects().list():
        row, last = _project_row(p)
        rows.append(row)
        if last:
            last_calls.append(last)
        if not Path(p.db).resolve().is_relative_to(folder.resolve()):   # e.g. a checkout's flowforge.db
            outside += row["size_bytes"]
    inside = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.is_dir() else 0
    total = inside + outside
    saved = settings_file.load()
    redactor = app_state_module.current.redactor if app_state_module.current else None
    data = {**saved.model_dump(), "version": home.version(), "install": home.install_kind(), "home": str(folder),
            "total_bytes": total, "projects": rows, "agent": _agent(last_calls),
            "vault": {"lock": Lock().state(), "store": "keychain" if _keychain_works() else "file"}}
    return redactor.redact(data) if redactor else data


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return _settings_data()


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    welcome_done: bool | None = None
    map_style: settings_file.MapStyle | None = None


@router.patch("/settings", dependencies=[Depends(from_this_machine)])
def change_settings(body: Change) -> dict[str, Any]:
    try:
        return settings_file.save(body.model_dump(exclude_unset=True)).model_dump()
    except ValueError:
        raise HTTPException(422, "That value isn't one of Settings' choices.") from None


def _project(project_id: str) -> Project:
    found = Projects().get(project_id)
    if found is None:
        raise HTTPException(404, "No such project.")
    return found


@router.delete("/projects/{project_id}/checks", dependencies=[Depends(from_this_machine)])
def clear_checks(project_id: str) -> dict[str, Any]:
    with _storage(_project(project_id)) as storage:
        if storage is not None:
            storage.clear_check_history()
    return {"id": project_id, "checks": 0}


@router.delete("/projects/{project_id}/confirmed", dependencies=[Depends(from_this_machine)])
def take_back_yeses(project_id: str) -> dict[str, Any]:
    with _storage(_project(project_id)) as storage:
        if storage is not None:
            storage.set_setting(CONFIRMED_SETTING, "[]")
    return {"id": project_id, "confirmed": []}


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version.split("+")[0])[:3])


@router.post("/settings/update-check", dependencies=[Depends(from_this_machine)])
def update_check() -> dict[str, Any]:
    """The only request Settings makes: pypi.org's latest version of flowforge-map, when you press the button."""
    current = home.version()
    try:
        with httpx.Client(transport=UPDATE_TRANSPORT, timeout=8) as client:
            latest = str(client.get(PYPI_URL).raise_for_status().json()["info"]["version"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"current": current, "latest": None, "newer": False,
                "error": "Couldn't reach pypi.org. Check your internet and try again."}
    return {"current": current, "latest": latest, "newer": _numbers(latest) > _numbers(current)}
