"""The flow map and the connector catalog (D17).

GET    /flow?layer=mine|planner          the map: blocks, lines, positions, critical path, counts
PUT    /flow/positions                   save block positions (drag end; Re-tidy sends replace=true)
POST   /flow/overrides                   one edit on top of the Planner's version (never the user's code)
DELETE /flow/overrides/{id}              undo one edit
DELETE /flow/nodes/{node_id}/overrides   back to the Planner's version for one block
GET    /flow/trace                       the traced test order the map replays
GET    /flow/analysis                    how the Planner drew the map (stages, log, files, calls, dropped)
GET    /flow/versions                    every version, newest first
POST   /flow/recheck                     a new pending version and its diff
GET    /flow/versions/{n}                a pending version's diff
POST   /flow/versions/{n}/accept         take the chosen changes; older versions stay listed
POST   /flow/versions/{n}/discard        keep the current map as it is
GET    /catalog                          every app, each on_map | connected | none
POST   /catalog/{id}/test                a mock test run: offline, canned, no key
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flowforge.connectors import catalog as catalog_mod
from flowforge.connectors.registry import _describe
from flowforge.flowmap.models import Override
from flowforge.flowmap.service import FlowService, OverrideError, VersionError
from flowforge.state import app_state

router = APIRouter()


def flows() -> FlowService:
    service = app_state().flows
    if service is None:
        raise HTTPException(503, "the flow map is not set up")
    return service


class Positions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    positions: dict[str, tuple[float, float]] = Field(max_length=500)
    replace: bool = False


class Choices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take: dict[str, bool | str] = Field(default_factory=dict)


@router.get("/flow")
def get_flow(layer: str = Query("mine", pattern="^(mine|planner)$")) -> dict[str, Any]:
    return flows().current(layer)


@router.put("/flow/positions")
def put_positions(body: Positions) -> dict[str, int]:
    flows().set_positions(body.positions, replace=body.replace)
    return {"saved": len(body.positions)}


@router.post("/flow/overrides", status_code=201)
def add_override(body: Annotated[Any, Body()]) -> dict[str, Any]:
    try:
        override = Override.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, _describe(exc)) from None
    try:
        return flows().add_override(override)
    except OverrideError as err:
        raise HTTPException(422, str(err)) from None


@router.delete("/flow/overrides/{override_id}", status_code=204)
def delete_override(override_id: int) -> None:
    if not flows().delete_override(override_id):
        raise HTTPException(404, "unknown edit")


@router.delete("/flow/nodes/{node_id}/overrides")
def reset_node(node_id: str) -> dict[str, int]:
    return {"removed": flows().reset_node(node_id)}


@router.get("/flow/trace")
def get_trace() -> dict[str, Any]:
    trace = flows().trace()
    if trace is None:
        raise HTTPException(404, "there is no traced test run yet")
    return trace


@router.get("/flow/analysis")
def get_analysis() -> dict[str, Any]:
    analysis = flows().analysis()
    if analysis is None:
        raise HTTPException(404, "the Planner hasn't drawn a map yet")
    return analysis


@router.get("/flow/versions")
def list_versions() -> list[dict[str, Any]]:
    return flows().versions()


@router.post("/flow/recheck")
def recheck() -> dict[str, Any]:
    try:
        return flows().recheck()
    except VersionError as err:
        raise HTTPException(409, str(err)) from None


@router.get("/flow/versions/{version}")
def pending_version(version: int) -> dict[str, Any]:
    try:
        return flows().pending_view(version)
    except VersionError as err:
        raise HTTPException(404, str(err)) from None


@router.post("/flow/versions/{version}/accept")
def accept_version(version: int, body: Choices) -> dict[str, Any]:
    try:
        return flows().accept(version, body.take)
    except VersionError as err:
        raise HTTPException(409, str(err)) from None


@router.post("/flow/versions/{version}/discard", status_code=204)
def discard_version(version: int) -> None:
    try:
        flows().discard(version)
    except VersionError as err:
        raise HTTPException(409, str(err)) from None


# --- catalog ----------------------------------------------------------------------------------------

def _connectors() -> dict[str, Any]:
    return {c.id: c for c in app_state().registry.all()}


def _on_map() -> set[str]:
    """Apps the code calls: confirmed app-call blocks on the Planner's own version (D17)."""
    service = app_state().flows
    flow = service.planner_flow() if service is not None else None
    if flow is None:
        return set()
    return {n.connector for n in flow.nodes if n.connector and n.status == "confirmed"
            and any(ev.confirms for ev in n.evidence)}


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return catalog_mod.catalog(_connectors(), _on_map())


@router.post("/catalog/{app_id}/test")
def test_app(app_id: str) -> dict[str, Any]:
    entry = catalog_mod.find(app_id, _connectors())
    if entry is None:
        raise HTTPException(404, "unknown app")
    return catalog_mod.mock_test(entry)
