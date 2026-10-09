"""The flow map's state (D17): the accepted Planner version, the user's edits on top, positions,
re-checks and their diffs. The API is a thin layer over this.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flowforge.connectors.models import Connector
from flowforge.flowmap.diff import apply_choices, default_take, diff
from flowforge.flowmap.models import CALL_KINDS, CONNECTOR_TYPE, Analysis, Evidence, Flow, FlowEdge, Override, Trace
from flowforge.flowmap.planner import Planner
from flowforge.flowmap.validate import FlowError, check, critical
from flowforge.storage import Storage

NOT_AVAILABLE = ("The Planner maps your repo from Phase 5. Until then, run `flowforge --example` "
                 "to see the map on an example app.")
FIXED_KINDS = ("gate", "start", "end")


class OverrideError(ValueError):
    """An edit that isn't allowed. One plain sentence."""


class VersionError(ValueError):
    pass


Edits = dict[str, list[dict[str, Any]]]


def merge(flow: Flow, overrides: list[tuple[int, Override]]) -> tuple[Flow, Edits, list[dict[str, Any]]]:
    """Apply the user's edits to a copy. Returns (flow, edits per block, hidden blocks).

    Edits naming a block that no longer exists (after a re-check) are skipped, not errors.
    """
    flow = flow.model_copy(deep=True)
    nodes = {n.id: n for n in flow.nodes}
    edits: dict[str, list[dict[str, Any]]] = {}
    hide: list[tuple[int, str]] = []

    def note(node_id: str, oid: int, o: Override) -> None:
        edits.setdefault(node_id, []).append({"id": oid, "op": o.op})

    for oid, o in overrides:
        if o.op == "add_node" and o.new_node is not None and o.new_node.id not in nodes:
            node = o.new_node.model_copy(update={"added_by": "user", "status": "confirmed"})
            flow.nodes.append(node)
            nodes[node.id] = node
            note(node.id, oid, o)
        elif o.node not in nodes:
            continue
        elif o.op == "set_connector":
            n = nodes[o.node]
            n.connector = o.connector
            if n.op is not None:
                n.op = n.op.model_copy(update={"model": None})
            note(o.node, oid, o)
        elif o.op == "rename":
            nodes[o.node].title = o.title or nodes[o.node].title
            note(o.node, oid, o)
        elif o.op == "confirm":
            n = nodes[o.node]
            n.status = "confirmed"
            n.evidence = [*n.evidence, Evidence(type="user", text="Confirmed by you.")]
            note(o.node, oid, o)
        elif o.op == "add_edge" and o.source in nodes:
            if not any(e.source == o.source and e.target == o.node for e in flow.edges):
                flow.edges.append(FlowEdge(id=_edge_id(flow, f"user_{o.source}_{o.node}"), source=o.source,
                                           target=o.node))
            # the "Yours" mark goes on the step you added, not on the Planner's block it connects to
            note(o.source if nodes[o.source].added_by == "user" else o.node, oid, o)
        elif o.op == "hide":
            hide.append((oid, o.node))

    hidden: list[dict[str, Any]] = []
    for oid, node_id in hide:
        node = nodes.get(node_id)
        if node is None or node.kind in FIXED_KINDS:
            continue
        ins = [e for e in flow.edges if e.target == node_id and e.kind != "retry"]
        outs = [e for e in flow.edges if e.source == node_id and e.kind != "retry"]
        flow.edges = [e for e in flow.edges if node_id not in (e.source, e.target)]
        for a in ins:   # bypass the hidden block so the flow stays connected
            for b in outs:
                if not any(e.source == a.source and e.target == b.target for e in flow.edges):
                    flow.edges.append(FlowEdge(id=_edge_id(flow, f"via_{a.source}_{b.target}"), source=a.source,
                                               target=b.target, kind=a.kind, when=a.when))
        flow.nodes = [n for n in flow.nodes if n.id != node_id]
        del nodes[node_id]
        hidden.append({"id": node_id, "title": node.title, "override": oid})
    flow.suggestions = [s for s in flow.suggestions if s.node in nodes]
    return flow, edits, hidden


def _edge_id(flow: Flow, base: str) -> str:
    base = base[:58]
    taken = {e.id for e in flow.edges}
    out, i = base, 2
    while out in taken:
        out, i = f"{base}_{i}", i + 1
    return out


class FlowService:
    def __init__(self, storage: Storage, connectors: Callable[[], dict[str, Connector]], planner: Planner | None):
        self.storage = storage
        self.connectors = connectors
        self.planner = planner

    # --- reading ---------------------------------------------------------------------------------

    def _base(self) -> tuple[dict[str, Any], Flow] | None:
        row = self.storage.latest_flow_version("accepted")
        if row is None:
            return None
        return row, Flow.model_validate(row["flow"])

    def planner_flow(self) -> Flow | None:
        """The accepted Planner version, without the user's edits."""
        base = self._base()
        return base[1] if base else None

    def overrides(self) -> list[tuple[int, Override]]:
        return [(oid, Override.model_validate(data)) for oid, data in self.storage.flow_overrides()]

    def current(self, layer: str = "mine") -> dict[str, Any]:
        base = self._base()
        if base is None:
            return {"available": False, "message": NOT_AVAILABLE}
        row, flow = base
        edits: dict[str, list[dict[str, Any]]] = {}
        hidden: list[dict[str, Any]] = []
        if layer == "mine":
            flow, edits, hidden = merge(flow, self.overrides())
        connectors = self.connectors()
        flow = check(flow, connectors, strict=False)   # a deleted app shows as unconfirmed, not an error
        cp = critical(flow)
        analysis = Analysis.model_validate(row["analysis"] or {"stages": []})
        on_path = set(cp.path)
        cp_edges = set(zip(cp.path, cp.path[1:], strict=False))
        planner_flow = Flow.model_validate(row["flow"])
        planner_connector = {n.id: n.connector for n in planner_flow.nodes}
        swapped = {node_id for node_id, items in edits.items() if any(i["op"] == "set_connector" for i in items)}
        current_connector = {n.id: n.connector for n in flow.nodes}
        tips = {s.node: s for s in flow.suggestions
                if s.node not in swapped and s.connector != current_connector.get(s.node)}
        nodes = []
        for n in flow.nodes:
            data = n.model_dump(mode="json")
            stats = analysis.stats.get(n.id)
            tip = tips.get(n.id)
            data.update({
                "yours": edits.get(n.id, []), "on_critical_path": n.id in on_path,
                "stats": stats.model_dump(mode="json") if stats else None,
                "tip": {"connector": tip.connector, "text": tip.text} if tip else None,
                "planner_connector": planner_connector.get(n.id),
            })
            nodes.append(data)
        edges = [{**e.model_dump(mode="json"), "on_critical_path": (e.source, e.target) in cp_edges}
                 for e in flow.edges]
        positions = {k: list(v) for k, v in analysis.positions.items()}
        positions.update({k: list(v) for k, v in self.storage.flow_positions().items()})
        used = {n.connector for n in flow.nodes if n.connector}
        apps = {cid: {"name": c.name, "type": c.type, "model": getattr(c.connection, "model", None)}
                for cid, c in connectors.items() if cid in used}
        pending = self.storage.latest_flow_version("pending")
        return {
            "available": True, "version": row["version"], "created_at": row["created_at"], "layer": layer,
            "fact_sheet_hash": row["fact_sheet_hash"], "nodes": nodes, "edges": edges, "hidden": hidden,
            "critical_path": {"path": cp.path, "length_ms": cp.length_ms, "bottleneck": cp.bottleneck},
            "positions": positions, "apps": apps,
            "counts": {"steps": len(flow.nodes), "unconfirmed": sum(n.status == "unconfirmed" for n in flow.nodes),
                       "gates": sum(n.kind == "gate" for n in flow.nodes), "edits": len(self.storage.flow_overrides())},
            "pending": pending["version"] if pending else None,
        }

    def trace(self) -> dict[str, Any] | None:
        base = self._base()
        if base is None or not base[0]["trace"]:
            return None
        return Trace.model_validate(base[0]["trace"]).model_dump(mode="json")

    def analysis(self) -> dict[str, Any] | None:
        base = self._base()
        if base is None:
            return None
        data = Analysis.model_validate(base[0]["analysis"] or {"stages": []}).model_dump(mode="json")
        data.pop("stats", None)
        data.pop("positions", None)
        return {**data, "version": base[0]["version"], "fact_sheet_hash": base[0]["fact_sheet_hash"]}

    def versions(self) -> list[dict[str, Any]]:
        return self.storage.flow_versions()

    # --- the first map ---------------------------------------------------------------------------

    def first_map(self) -> int | None:
        """Draw the first map if there is none. Returns its version, or None without a Planner."""
        if self.planner is None or self.storage.count_flow_versions():
            return None
        draft = self.planner.analyze(0)
        check(draft.flow, self.connectors())   # the Planner's output must be a valid map
        return self.storage.add_flow_version("accepted", draft.flow.model_dump(mode="json"),
                                             draft.trace.model_dump(mode="json") if draft.trace else None,
                                             draft.analysis.model_dump(mode="json"), draft.fact_sheet_hash)

    # --- edits -----------------------------------------------------------------------------------

    def add_override(self, override: Override) -> dict[str, Any]:
        base = self._base()
        if base is None:
            raise OverrideError("there is no map to edit yet")
        _, flow = base
        connectors = self.connectors()
        merged = check(merge(flow, self.overrides())[0], connectors, strict=False)  # statuses as drawn
        node = merged.node(override.node) if override.node else None
        if override.op != "add_node" and node is None:
            raise OverrideError(f"there is no block '{override.node}' on the map")
        if override.op == "hide" and node is not None and node.kind in FIXED_KINDS:
            raise OverrideError("gates, starts and ends can't be hidden; gates always stay (D14)")
        if override.op == "set_connector" and node is not None:
            if node.kind not in CALL_KINDS:
                raise OverrideError(f"'{node.title}' doesn't call an app, so it has no app to swap")
            _need_connector(override.connector, node.kind, connectors)
        if override.op == "confirm" and node is not None and node.status != "unconfirmed":
            raise OverrideError(f"'{node.title}' is already confirmed")
        if override.op == "add_node" and override.new_node is not None:
            new = override.new_node
            if merged.node(new.id) is not None or any(n.id == new.id for n in flow.nodes):
                raise OverrideError(f"there is already a block called '{new.id}'")
            if new.kind not in CALL_KINDS | {"code"}:
                raise OverrideError("you can add app calls and code steps; the Planner draws the rest")
            if new.kind in CALL_KINDS:
                _need_connector(new.connector, new.kind, connectors)
            override = override.model_copy(update={"new_node": new.model_copy(update={
                "added_by": "user", "status": "confirmed",
                "evidence": new.evidence or [Evidence(type="user", text="Added by you.")]})})
        if override.op == "add_edge" and merged.node(override.source or "") is None:
            raise OverrideError(f"there is no block '{override.source}' on the map")
        trial, _, _ = merge(flow, [*self.overrides(), (0, override)])
        try:
            check(trial, connectors)
        except FlowError as err:
            raise OverrideError(str(err)) from None
        oid = self.storage.add_flow_override(override.model_dump(mode="json", exclude_none=True))
        return {"id": oid, **override.model_dump(mode="json", exclude_none=True)}

    def delete_override(self, oid: int) -> bool:
        return self.storage.delete_flow_overrides([oid]) > 0

    def reset_node(self, node_id: str) -> int:
        """Back to the Planner's version: drop every edit on this block (and a block you added, with its lines)."""
        ids = []
        for oid, o in self.overrides():
            if o.node == node_id or (o.op == "add_node" and o.new_node is not None and o.new_node.id == node_id) \
                    or (o.op == "add_edge" and o.source == node_id and self._user_added(node_id)):
                ids.append(oid)
        return self.storage.delete_flow_overrides(ids)

    def _user_added(self, node_id: str) -> bool:
        return any(o.op == "add_node" and o.new_node is not None and o.new_node.id == node_id
                   for _, o in self.overrides())

    def set_positions(self, positions: dict[str, tuple[float, float]], replace: bool = False) -> None:
        self.storage.put_flow_positions(positions, replace=replace)

    # --- re-check --------------------------------------------------------------------------------

    def recheck(self) -> dict[str, Any]:
        if self.planner is None:
            raise VersionError(NOT_AVAILABLE)
        base = self._base()
        if base is None:
            raise VersionError("there is no map to re-check yet")
        row, old = base
        draft = self.planner.analyze(self.storage.count_flow_versions())
        try:
            check(draft.flow, self.connectors())
        except FlowError as err:
            raise VersionError(f"the Planner's new map isn't valid: {err}") from None
        pending = self.storage.latest_flow_version("pending")
        if pending is not None:
            self.storage.update_flow_version(pending["version"], "discarded")
        changes = diff(old, draft.flow, self.overrides(), draft.analysis.notes)
        version = self.storage.add_flow_version(
            "pending", draft.flow.model_dump(mode="json"), draft.trace.model_dump(mode="json") if draft.trace else None,
            draft.analysis.model_dump(mode="json"), draft.fact_sheet_hash, changes=changes)
        return self.pending_view(version)

    def pending_view(self, version: int) -> dict[str, Any]:
        row = self.storage.flow_version(version)
        if row is None or row["status"] != "pending":
            raise VersionError(f"version {version} is not waiting for a decision")
        base = self._base()
        new = Flow.model_validate(row["flow"])
        return {"version": version, "base_version": base[0]["version"] if base else None,
                "created_at": row["created_at"], "fact_sheet_hash": row["fact_sheet_hash"],
                "changes": row["changes"] or [], "default_take": default_take(row["changes"] or []),
                "nodes": [n.model_dump(mode="json") for n in new.nodes],
                "edges": [e.model_dump(mode="json") for e in new.edges]}

    def accept(self, version: int, take: dict[str, bool | str]) -> dict[str, Any]:
        row = self.storage.flow_version(version)
        if row is None or row["status"] != "pending":
            raise VersionError(f"version {version} is not waiting for a decision")
        base = self._base()
        if base is None:
            raise VersionError("there is no map to update")
        changes = row["changes"] or []
        known = {c["id"] for c in changes}
        unknown = sorted(set(take) - known)
        if unknown:
            raise VersionError(f"unknown change: {', '.join(unknown)}")
        flow, drop_edits = apply_choices(base[1], Flow.model_validate(row["flow"]), changes, take)
        try:
            check(flow, self.connectors())
        except FlowError as err:
            raise VersionError(f"that mix of changes isn't a valid map: {err}") from None
        self.storage.update_flow_version(version, "accepted", flow.model_dump(mode="json"))
        stale = [oid for oid, o in self.overrides() if o.node in drop_edits]
        self.storage.delete_flow_overrides(stale)
        return self.current()

    def discard(self, version: int) -> None:
        row = self.storage.flow_version(version)
        if row is None or row["status"] != "pending":
            raise VersionError(f"version {version} is not waiting for a decision")
        self.storage.update_flow_version(version, "discarded")


def _need_connector(connector_id: str | None, kind: str, connectors: dict[str, Connector]) -> None:
    if not connector_id or connector_id not in connectors:
        raise OverrideError(f"'{connector_id}' isn't connected; add it from the catalog first")
    want = CONNECTOR_TYPE[kind]
    if connectors[connector_id].type != want:
        raise OverrideError(f"'{connector_id}' is a {connectors[connector_id].type} app; this step needs a {want} app")


def example_edits(service: FlowService, overrides: list[dict[str, Any]],
                  positions: dict[str, tuple[float, float]]) -> None:
    """Example mode: seed the project's own edits and the designed layout once (D16, D17)."""
    if service.storage.flow_overrides():
        return
    for data in overrides:
        service.add_override(Override.model_validate(data))
    if not service.storage.flow_positions():
        service.set_positions(positions)
