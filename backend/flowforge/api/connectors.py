"""Connectors: list, read, create, edit, delete, logo, test, activity, presets (D10, D12, D16).

Keys are references only: responses carry `secret: {"ref", "status": "set" | "missing"}`, never
a value. Bodies are validated by hand so a rejected body is never echoed back (it might hold a
pasted key). Connectors from connectors.json are read-only here (D16).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from flowforge.connectors.models import Connector, parse_connector
from flowforge.connectors.presets import CUSTOM, DEFAULT_CONNECTORS, PRESETS
from flowforge.connectors.registry import ConnectorFileError, _describe, check_references
from flowforge.connectors.runtime import build_node
from flowforge.home import flowforge_home
from flowforge.nodes.base import NodeError
from flowforge.nodes.local_node import LocalNode
from flowforge.nodes.mcp_node import MCPNode
from flowforge.security.logfilter import secret_values_for
from flowforge.state import AppState, app_state

MCP_TIMEOUT_S = 15
MAX_LOGO_BYTES = 1024 * 1024
LOGO_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}

router = APIRouter()


# --- helpers ------------------------------------------------------------------------------------------

def secret_status(connector: Connector, example: bool = False) -> dict[str, str] | None:
    """"set" or "missing", never the value. In example mode a missing key reads "example"."""
    ref = connector.secret_ref
    if ref is None:
        return None
    name = ref.split(":", 1)[1]
    if ref.startswith("env:") and os.environ.get(name):
        return {"ref": ref, "status": "set"}
    return {"ref": ref, "status": "example" if example else "missing"}


def view(connector: Connector, s: AppState) -> dict[str, Any]:
    data = connector.model_dump(mode="json")
    data["secret"] = secret_status(connector, s.example)
    data["managed_by"] = "file" if connector.id in s.file_managed else "app"
    data["deletable"] = connector.id not in DEFAULT_CONNECTORS and connector.id not in s.file_managed
    data["is_default"] = connector.id in DEFAULT_CONNECTORS
    if connector.style.logo.type == "upload":
        data["logo_url"] = f"/connectors/{connector.id}/logo"
    return data


def get_connector(connector_id: str) -> Connector:
    connector = app_state().registry.get(connector_id)
    if connector is None:
        raise HTTPException(404, "unknown connector")
    return connector


def editable(connector_id: str) -> Connector:
    connector = get_connector(connector_id)
    if connector_id in app_state().file_managed:
        raise HTTPException(409, f"'{connector_id}' is managed by connectors.json; edit that file instead")
    return connector


def parse_body(body: Any) -> Connector:
    try:
        connector = parse_connector(body)
    except ValidationError as exc:
        raise HTTPException(422, _describe(exc)) from None  # field paths and messages only, no values
    if connector.secret_ref and connector.secret_ref.startswith("vault:"):
        raise HTTPException(422, "vault: references need the vault, which arrives in Phase 4; use env:NAME")
    return connector


def install(connector: Connector, s: AppState) -> None:
    """Save, then swap in a fresh node and bucket. Running runs keep their snapshot (D16)."""
    others = [c for c in s.registry.all() if c.id != connector.id]
    try:
        check_references([*others, connector])
    except ConnectorFileError as exc:
        raise HTTPException(422, str(exc)) from None
    s.registry.save(connector)
    node, bucket = build_node(connector)
    old = s.nodes.get(connector.id)
    if old is not None:
        s.retired_nodes.append(old)
    s.nodes[connector.id] = node
    if connector.id == "nim":
        s.nodes["llm"] = node
    if bucket is not None and node.rate_limit_key:
        s.rate_limits[node.rate_limit_key] = bucket
    else:
        s.rate_limits.pop(connector.id, None)
    refresh_redaction(s)


def refresh_redaction(s: AppState) -> None:
    s.redactor.set_values(secret_values_for(s.registry.all()))


# --- routes -------------------------------------------------------------------------------------------

@router.get("/connectors")
def list_connectors() -> list[dict[str, Any]]:
    s = app_state()
    return [view(c, s) for c in s.registry.all()]


@router.get("/connectors/{connector_id}")
def read_connector(connector_id: str) -> dict[str, Any]:
    return view(get_connector(connector_id), app_state())


@router.post("/connectors", status_code=201)
def create_connector(body: Annotated[Any, Body()]) -> dict[str, Any]:
    s = app_state()
    connector = parse_body(body)
    if s.registry.get(connector.id) is not None:
        raise HTTPException(409, f"a connector called '{connector.id}' already exists")
    install(connector, s)
    return view(connector, s)


@router.put("/connectors/{connector_id}")
def update_connector(connector_id: str, body: Annotated[Any, Body()]) -> dict[str, Any]:
    s = app_state()
    current = editable(connector_id)
    connector = parse_body(body)
    if connector.id != connector_id:
        raise HTTPException(422, "the id in the body must match the URL; ids can't be renamed")
    if connector.style.logo.type == "upload" and current.style.logo != connector.style.logo:
        raise HTTPException(422, "upload a logo through /connectors/{id}/logo")
    install(connector.model_copy(update={"created_at": current.created_at}), s)
    return view(connector, s)


@router.delete("/connectors/{connector_id}", status_code=204)
def delete_connector(connector_id: str) -> Response:
    s = app_state()
    editable(connector_id)
    if connector_id in DEFAULT_CONNECTORS:
        raise HTTPException(409, f"'{connector_id}' is a default connector and can't be deleted")
    users = [c.id for c in s.registry.all() if c.fallback == connector_id]
    if users:
        raise HTTPException(409, f"'{connector_id}' is the fallback for {', '.join(users)}; change those first")
    s.registry.delete(connector_id)
    node = s.nodes.pop(connector_id, None)
    if node is not None:
        s.retired_nodes.append(node)
    s.rate_limits.pop(connector_id, None)
    refresh_redaction(s)
    return Response(status_code=204)


@router.post("/connectors/{connector_id}/logo")
async def upload_logo(connector_id: str, file: UploadFile) -> dict[str, Any]:
    """PNG, JPEG or WebP, at most 1 MB, checked by content (CLAUDE.md §6.5). No SVG."""
    s = app_state()
    connector = editable(connector_id)
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(413, "logos must be 1 MB or smaller")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif data.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise HTTPException(415, "logos must be PNG, JPEG or WebP images")
    folder = flowforge_home() / "logos"
    folder.mkdir(parents=True, exist_ok=True)
    for old in LOGO_TYPES:
        (folder / f"{connector_id}.{old}").unlink(missing_ok=True)
    (folder / f"{connector_id}.{ext}").write_bytes(data)
    data = connector.model_dump(mode="json")
    data["style"]["logo"] = {"type": "upload", "file": f"{connector_id}.{ext}"}
    updated = parse_connector(data)
    s.registry.save(updated)
    return view(updated, s)


@router.get("/connectors/{connector_id}/logo")
def get_logo(connector_id: str) -> FileResponse:
    logo = get_connector(connector_id).style.logo
    if logo.type != "upload":
        raise HTTPException(404, "this connector has no uploaded logo")
    name, _, ext = logo.file.rpartition(".")
    path = flowforge_home() / "logos" / f"{connector_id}.{ext}"
    if name != connector_id or ext not in LOGO_TYPES or not path.is_file():
        raise HTTPException(404, "logo file missing")
    return FileResponse(path, media_type=LOGO_TYPES[ext],
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})


@router.post("/connectors/{connector_id}/test")
async def test_connector(connector_id: str) -> dict[str, Any]:
    """One harmless check. MCP: list its tools. Local: the program and folder exist."""
    s = app_state()
    connector = get_connector(connector_id)
    node = s.nodes.get(connector_id)
    if connector.type in ("llm", "http"):
        raise HTTPException(501, f"Testing {connector.type} connectors arrives in Phase 4")
    try:
        if isinstance(node, MCPNode):
            tools = await asyncio.wait_for(node.list_tools(), MCP_TIMEOUT_S)
            message = f"Connected. {len(tools)} tool{'s' if len(tools) != 1 else ''} found."
        elif isinstance(node, LocalNode):
            node._program(node._env())
            node._workdir(None)
            message = "Ready. The program and its folder were found."
        else:
            raise HTTPException(409, "this connector has no node; restart FlowForge")
        result = {"ok": True, "message": message}
    except (NodeError, TimeoutError) as exc:
        result = {"ok": False, "message": s.redactor.redact_text(str(exc) or "timed out")}
    s.connector_tests[connector_id] = {**result, "at": datetime.now().astimezone().isoformat(timespec="seconds")}
    return result


def connector_steps(s: AppState, recent_runs: int = 50) -> dict[str, list[dict[str, Any]]]:
    """Steps from recent stored runs, grouped by the connector that answered them, newest first."""
    by_connector: dict[str, list[dict[str, Any]]] = {}
    for summary, result in s.storage.recent_results(limit=recent_runs):
        started = datetime.fromisoformat(summary["started_at"])
        titles = {o["id"]: o["title"] for o in json.loads(summary.get("steps_json") or "[]")}
        for step in result["steps"].values():
            connector_id = step.get("answered_by")
            if connector_id is None or step.get("started_at") is None:
                continue
            offset = step.get("finished_at") or step["started_at"]
            duration = None
            if step.get("finished_at") is not None:
                duration = (step["finished_at"] - step["started_at"]) * 1000
            by_connector.setdefault(connector_id, []).append({
                "run_id": summary["id"], "plan": summary["workflow_name"] or summary["workflow_id"],
                "step_id": step["step_id"], "title": titles.get(step["step_id"], step["step_id"]),
                "state": step["state"], "error": step.get("error"),
                "cache_hit": step.get("cache_hit"), "attempts": step.get("attempts", 0), "duration_ms": duration,
                "at": (started + timedelta(seconds=offset)).isoformat(timespec="milliseconds")})
    for items in by_connector.values():
        items.sort(key=lambda i: i["at"], reverse=True)
    return by_connector


@router.get("/connectors/{connector_id}/activity")
def connector_activity(connector_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """This connector's most recent steps, newest first (from stored results, D16)."""
    get_connector(connector_id)
    return connector_steps(app_state()).get(connector_id, [])[:limit]


@router.get("/connectors/{connector_id}/tools")
async def connector_tools(connector_id: str) -> list[dict[str, Any]]:
    node = app_state().nodes.get(connector_id)
    if node is None:
        raise HTTPException(404, "unknown connector")
    if not isinstance(node, MCPNode):
        raise HTTPException(422, f"'{connector_id}' is not an MCP connector")
    try:
        return await asyncio.wait_for(node.list_tools(), MCP_TIMEOUT_S)
    except (NodeError, TimeoutError) as exc:
        raise HTTPException(502, f"could not list tools: {str(exc) or type(exc).__name__}") from exc


@router.get("/presets")
def list_presets() -> list[dict[str, Any]]:
    """Ready-made connectors and one Custom template per type, for "Add an app"."""
    presets = [{**c.model_dump(mode="json"), "preset": c.id} for c in PRESETS.values()]
    custom = [{"preset": f"custom-{t}", "name": f"Custom {t}", **template} for t, template in CUSTOM.items()]
    return presets + custom
