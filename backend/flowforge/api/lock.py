"""The locked key view (D37): the only place FlowForge shows a key's value. A password and the code from your phone
open it for five minutes; values come one at a time, are never stored or logged, and the agent's MCP server has no way
to them. Every route answers only to the dashboard on this machine (D36's Host/Origin guard).

GET  /lock            {state: none|pending|on, open, seconds_left, reset_at}
POST /lock/setup      {password} → {uri, qr}: the phone's secret, shown once
POST /lock/confirm    {password, code} → {state: "on"}
POST /lock/open       {password, code} → {open: true, seconds_left}, with an httpOnly SameSite=Strict cookie
POST /lock/close
GET  /keys/hidden     open only: [{where: code|saved|env, name, ref}], no values
POST /keys/reveal     open only: {where, name, ref} → {value}
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from flowforge.api.keys import from_this_machine
from flowforge.api.scan import repo_path
from flowforge.scan import scan as scan_repo
from flowforge.scan.files import language
from flowforge.security.finders import find_keys, is_secret_name, key_span
from flowforge.security.findings import env_name
from flowforge.security.keystore import KeyStore
from flowforge.security.lock import SESSION_S, Lock, LockError
from flowforge.state import app_state

router = APIRouter(dependencies=[Depends(from_this_machine)])

COOKIE = "ff_keyview"
_CONFIG_PAIR = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*"((?:[^"\\]|\\.)*)"')


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Password(_Body):
    password: str


class PasswordCode(_Body):
    password: str
    code: str


class Which(_Body):
    where: str
    name: str
    ref: str | None = None


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _session(request: Request) -> str:
    token = request.cookies.get(COOKIE)
    if not Lock().valid(token):
        raise HTTPException(401, "The key view is locked: open it with your password and the code from your phone.")
    return token or ""


def _repo() -> Path:
    repo = repo_path(app_state())
    if repo is None or not repo.is_dir():
        raise HTTPException(409, "Map a folder first.")
    return repo


def _in_code(repo: Path) -> list[tuple[str, str, str]]:
    """(name, ref, value) for each key written in the code or an MCP config, as the scan finds them now."""
    import json

    out = []
    for f in scan_repo(repo).findings:
        path, line = f.ref.rsplit(":", 1)
        try:
            text = (repo / path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if f.kind == "key_in_code":
            lang = language(path)
            span = key_span(text, lang, int(line))
            hit = next((h for h in find_keys(text, lang) if h.line == int(line)), None)
            if span and hit:
                out.append((env_name(hit.name, "API_KEY" if hit.label == "secret" else hit.label), f.ref, span[2]))
        elif f.kind == "key_in_config":
            lines = text.splitlines()
            source = lines[int(line) - 1] if 0 < int(line) <= len(lines) else ""
            pair = next((m for m in _CONFIG_PAIR.finditer(source) if not m.group(2).startswith("${")), None)
            if pair:
                out.append((pair.group(1), f.ref, json.loads(f'"{pair.group(2)}"')))
    return out


def _in_env(repo: Path) -> dict[str, str]:
    from dotenv import dotenv_values

    path = repo / ".env"
    found = dotenv_values(path) if path.is_file() else {}
    return {k: v for k, v in found.items() if v and is_secret_name(k)}


@router.get("/lock")
def lock_state(request: Request, response: Response) -> dict[str, Any]:
    _no_store(response)
    lock, token = Lock(), request.cookies.get(COOKIE)
    return {"state": lock.state(), "open": lock.valid(token), "seconds_left": lock.seconds_left(token),
            "reset_at": lock.reset_at()}


@router.post("/lock/setup")
def setup(body: Password, response: Response) -> dict[str, Any]:
    import segno

    _no_store(response)
    try:
        uri = Lock().setup(body.password)
    except LockError as e:
        raise HTTPException(409, str(e)) from None
    svg = segno.make(uri, error="m").svg_inline(scale=6, border=2, dark="#0F1D26", light="#FFFFFF")
    return {"uri": uri, "qr": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()}


@router.post("/lock/confirm")
def confirm(body: PasswordCode) -> dict[str, Any]:
    try:
        Lock().confirm(body.password, body.code)
    except LockError as e:
        raise HTTPException(403, str(e)) from None
    return {"state": "on"}


@router.post("/lock/open")
def open_view(body: PasswordCode, response: Response) -> dict[str, Any]:
    lock = Lock()
    try:
        token = lock.open(body.password, body.code)
    except LockError as e:
        raise HTTPException(403, str(e)) from None
    response.set_cookie(COOKIE, token, max_age=SESSION_S, httponly=True, samesite="strict", path="/")
    _no_store(response)
    return {"open": True, "seconds_left": lock.seconds_left(token)}


@router.post("/lock/close")
def close_view(request: Request, response: Response) -> dict[str, Any]:
    Lock().close(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"open": False}


@router.get("/keys/hidden")
def hidden(response: Response, _: str = Depends(_session)) -> dict[str, Any]:
    """What the open view can show, without a value: keys in code, saved in FlowForge, in .env."""
    _no_store(response)
    repo = _repo()
    items = [{"where": "code", "name": name, "ref": ref} for name, ref, _value in _in_code(repo)]
    items += [{"where": "saved", "name": name, "ref": None} for name in KeyStore(repo).names()]
    items += [{"where": "env", "name": name, "ref": ".env"} for name in _in_env(repo)]
    return {"items": items}


@router.post("/keys/reveal")
def reveal(body: Which, response: Response, _: str = Depends(_session)) -> dict[str, Any]:
    """One value, for the open view only. Never stored, never logged, never cached."""
    _no_store(response)
    repo = _repo()
    value: str | None = None
    if body.where == "code":
        value = next((v for name, ref, v in _in_code(repo) if name == body.name and ref == body.ref), None)
    elif body.where == "saved":
        value = KeyStore(repo).env().get(body.name)
    elif body.where == "env":
        value = _in_env(repo).get(body.name)
    if value is None:
        raise HTTPException(404, "That key isn't there any more.")
    return {"value": value}
