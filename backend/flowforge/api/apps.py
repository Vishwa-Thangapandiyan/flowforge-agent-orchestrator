"""The agent's app runs (D43). The coding agent's MCP server asks here, with the token from `server.json`, to run the
user's app; a new command waits for the user's Allow on the dashboard (unless `approve_runs` is off), then runs with
the project's keys filled in. Nothing here answers with a value: commands are shown as the agent wrote them (masks),
keys by name, output masked.

POST /apps/run                     {argv} + X-FlowForge-Token → 201 running {run} | 202 waiting {request} | 409 missing
GET  /apps/requests/{id}           + token → {state: waiting|allowed|denied, run?}
GET  /apps                         the dashboard: {requests (waiting), runs, approve_runs}
POST /apps/requests/{id}/allow     the dashboard on this machine → {state: allowed, run}
POST /apps/requests/{id}/deny      → {state: denied}
GET  /apps/runs/{id}/output        ?since=N → {status, code, lines: [[n, text]]}
POST /apps/runs/{id}/stop          → {id, stopped}
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from flowforge import settings
from flowforge import state as app_state_module
from flowforge.api.keys import from_this_machine
from flowforge.api.scan import repo_path
from flowforge.apps import Runs
from flowforge.home import flowforge_home
from flowforge.security.keystore import KeyStore, _write_private
from flowforge.security.masks import MissingKeys, masks_in
from flowforge.state import AppState, app_state

router = APIRouter()

APPROVED_SETTING = "approved_runs"   # the commands (argument lists, as JSON) the user allowed in this project
RUNS = Runs()
_requests: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_token = secrets.token_urlsafe(32)


class RunAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    argv: list[str] = Field(min_length=1)


# where FlowForge is, for the agent's MCP server

def server_file() -> Path:
    return flowforge_home() / "server.json"


def token() -> str:
    return _token


def started() -> None:
    """At start-up: a fresh token, and server.json (port + token, only you can read it) when the port is known."""
    global _token
    _token = secrets.token_urlsafe(32)
    RUNS.clear()
    with _lock:
        _requests.clear()
    port = os.getenv("FLOWFORGE_PORT")
    if port and port.isdigit():
        _write_private(server_file(), json.dumps({"port": int(port), "token": _token, "pid": os.getpid()}).encode())


def stopping() -> None:
    """At shutdown: every run stops, and server.json goes if it is still ours."""
    RUNS.stop_all()
    found = read_server_file()
    if found and found.get("pid") == os.getpid():
        server_file().unlink(missing_ok=True)


def read_server_file() -> dict[str, Any] | None:
    try:
        found = json.loads(server_file().read_text())
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _agent(x_flowforge_token: str | None = Header(default=None)) -> None:
    if not x_flowforge_token or not secrets.compare_digest(x_flowforge_token, _token):
        raise HTTPException(403, "Only FlowForge's own MCP server can ask to run your app.")


# helpers

def _project_id() -> str:
    return app_state_module.project_var.get() or app_state_module.default_id or "default"


def _repo(s: AppState) -> Path:
    repo = repo_path(s)
    if repo is None or not repo.is_dir():
        raise HTTPException(409, "Map a folder first: the app runs in its project's folder.")
    return repo


def _approved(s: AppState) -> list[list[str]]:
    try:
        found = json.loads(s.storage.setting(APPROVED_SETTING) or "[]")
    except ValueError:
        return []
    return [a for a in found if isinstance(a, list)] if isinstance(found, list) else []


def _start(s: AppState, argv: list[str]) -> dict[str, Any]:
    repo = _repo(s)
    values = KeyStore(repo).env()
    s.redactor.learn(values.values())   # the app's output is masked with every saved value (D36)
    try:
        run = RUNS.start(_project_id(), argv, repo, values, s.redactor.redact_text)
    except MissingKeys as e:
        raise HTTPException(409, str(e)) from None
    return run.summary()


def _check_masks(s: AppState, argv: list[str]) -> list[str]:
    """The key names the app will get; refuses masks for keys that aren't saved, before anything is asked."""
    store = KeyStore(_repo(s))
    missing = masks_in(argv, {}) - set(store.names())
    if missing:
        raise HTTPException(409, str(MissingKeys(missing)))
    return sorted(set(store.names()) | masks_in(argv, {}))


# the agent's side

@router.post("/apps/run", dependencies=[Depends(_agent), Depends(from_this_machine)])
def run_app(body: RunAsk, response: Response) -> dict[str, Any]:
    s = app_state()
    keys = _check_masks(s, body.argv)
    if not settings.load().approve_runs or body.argv in _approved(s):
        response.status_code = 201
        return {"state": "running", "run": _start(s, body.argv)}
    request = {"id": uuid.uuid4().hex[:12], "project": _project_id(), "argv": body.argv, "keys": keys,
               "at": time.time(), "state": "waiting", "run": None}
    with _lock:
        _requests[request["id"]] = request
    response.status_code = 202
    return {"state": "waiting", "request": _public(request)}


def _public(request: dict[str, Any]) -> dict[str, Any]:
    return {k: request[k] for k in ("id", "argv", "keys", "at", "state", "run")}


def _request(request_id: str) -> dict[str, Any]:
    with _lock:
        found = _requests.get(request_id)
    if found is None or found["project"] != _project_id():
        raise HTTPException(404, "No such request.")
    return found


@router.get("/apps/requests/{request_id}", dependencies=[Depends(_agent)])
def request_state(request_id: str) -> dict[str, Any]:
    return _public(_request(request_id))


# the user's side

@router.get("/apps")
def apps() -> dict[str, Any]:
    pid = _project_id()
    with _lock:
        waiting = [_public(r) for r in _requests.values() if r["project"] == pid and r["state"] == "waiting"]
    return {"requests": waiting, "runs": [r.summary() for r in RUNS.list(pid)],
            "approve_runs": settings.load().approve_runs}


@router.post("/apps/requests/{request_id}/allow", dependencies=[Depends(from_this_machine)])
def allow(request_id: str) -> dict[str, Any]:
    s = app_state()
    request = _request(request_id)
    if request["state"] != "waiting":
        return _public(request)
    approved = _approved(s)
    if request["argv"] not in approved:
        s.storage.set_setting(APPROVED_SETTING, json.dumps([*approved, request["argv"]]))
    request["run"] = _start(s, request["argv"])
    request["state"] = "allowed"
    return _public(request)


@router.post("/apps/requests/{request_id}/deny", dependencies=[Depends(from_this_machine)])
def deny(request_id: str) -> dict[str, Any]:
    request = _request(request_id)
    if request["state"] == "waiting":
        request["state"] = "denied"
    return _public(request)


def _run(run_id: str):
    run = RUNS.get(run_id)
    if run is None or run.project != _project_id():
        raise HTTPException(404, "No such run.")
    return run


@router.get("/apps/runs/{run_id}/output")
def output(run_id: str, since: int = 0) -> dict[str, Any]:
    run = _run(run_id)
    return {**run.summary(), "lines": [list(x) for x in run.output(since)]}


@router.post("/apps/runs/{run_id}/stop", dependencies=[Depends(from_this_machine)])
def stop(run_id: str) -> dict[str, Any]:
    run = _run(run_id)
    return {"id": run.id, "stopped": RUNS.stop(run.id)}
