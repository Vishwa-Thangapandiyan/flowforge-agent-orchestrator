"""The maps and the connector catalog (D17, D21).

Every /flow route takes ?map=deps|flow: the dependency map from a scan (the default) or the flow map.

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


MapId = Annotated[str, Query(alias="map", pattern="^(deps|flow)$")]


def flows(map_id: str = "deps") -> FlowService:
    service = (app_state().flows or {}).get(map_id)
    if service is None:
        raise HTTPException(503, "the map is not set up")
    return service


class Positions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    positions: dict[str, tuple[float, float]] = Field(max_length=500)
    replace: bool = False


class Choices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take: dict[str, bool | str] = Field(default_factory=dict)


@router.get("/flow")
def get_flow(layer: str = Query("mine", pattern="^(mine|planner)$"), map_id: MapId = "deps") -> dict[str, Any]:
    return flows(map_id).current(layer)


@router.put("/flow/positions")
def put_positions(body: Positions, map_id: MapId = "deps") -> dict[str, int]:
    flows(map_id).set_positions(body.positions, replace=body.replace)
    return {"saved": len(body.positions)}


@router.post("/flow/overrides", status_code=201)
def add_override(body: Annotated[Any, Body()], map_id: MapId = "deps") -> dict[str, Any]:
    try:
        override = Override.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(422, _describe(exc)) from None
    try:
        return flows(map_id).add_override(override)
    except OverrideError as err:
        raise HTTPException(422, str(err)) from None


@router.delete("/flow/overrides/{override_id}", status_code=204)
def delete_override(override_id: int, map_id: MapId = "deps") -> None:
    if not flows(map_id).delete_override(override_id):
        raise HTTPException(404, "unknown edit")


@router.delete("/flow/nodes/{node_id}/overrides")
def reset_node(node_id: str, map_id: MapId = "deps") -> dict[str, int]:
    return {"removed": flows(map_id).reset_node(node_id)}


@router.get("/flow/trace")
def get_trace(map_id: MapId = "deps") -> dict[str, Any]:
    trace = flows(map_id).trace()
    if trace is None:
        raise HTTPException(404, "there is no traced test run yet")
    return trace


@router.get("/flow/analysis")
def get_analysis(map_id: MapId = "deps") -> dict[str, Any]:
    analysis = flows(map_id).analysis()
    if analysis is None:
        raise HTTPException(404, "the Planner hasn't drawn a map yet")
    return analysis


@router.get("/flow/versions")
def list_versions(map_id: MapId = "deps") -> list[dict[str, Any]]:
    return flows(map_id).versions()


@router.post("/flow/recheck")
def recheck(map_id: MapId = "deps") -> dict[str, Any]:
    try:
        return flows(map_id).recheck()
    except VersionError as err:
        raise HTTPException(409, str(err)) from None


@router.get("/flow/versions/{version}")
def pending_version(version: int, map_id: MapId = "deps") -> dict[str, Any]:
    try:
        return flows(map_id).pending_view(version)
    except VersionError as err:
        raise HTTPException(404, str(err)) from None


@router.post("/flow/versions/{version}/accept")
def accept_version(version: int, body: Choices, map_id: MapId = "deps") -> dict[str, Any]:
    try:
        return flows(map_id).accept(version, body.take)
    except VersionError as err:
        raise HTTPException(409, str(err)) from None


@router.post("/flow/versions/{version}/discard", status_code=204)
def discard_version(version: int, map_id: MapId = "deps") -> None:
    try:
        flows(map_id).discard(version)
    except VersionError as err:
        raise HTTPException(409, str(err)) from None


# --- catalog ----------------------------------------------------------------------------------------

def _connectors() -> dict[str, Any]:
    return {c.id: c for c in app_state().registry.all()}


def _on_map() -> set[str]:
    """Apps the code calls: confirmed blocks with evidence on either map's Planner version (D17, D21). A block
    counts by its connected app or, on the dependency map, by the known service it was recognised as."""
    found: set[str] = set()
    for service in (app_state().flows or {}).values():
        flow = service.planner_flow()
        if flow is None:
            continue
        found |= {app for n in flow.nodes if n.status == "confirmed" and any(ev.confirms for ev in n.evidence)
                  for app in (n.connector, n.catalog) if app}
    return found


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return catalog_mod.catalog(_connectors(), _on_map())


@router.post("/catalog/{app_id}/test")
def test_app(app_id: str) -> dict[str, Any]:
    entry = catalog_mod.find(app_id, _connectors())
    if entry is None:
        raise HTTPException(404, "unknown app")
    return catalog_mod.mock_test(entry)
