"""Re-check diff (D17). Re-checking never overwrites the map. It lists what changed between the
accepted version and the new one, and the user picks what to take.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flowforge.flowmap.models import Flow, FlowEdge, FlowNode, Override

CompareFields = ("kind", "title", "connector", "op", "condition", "what", "status")
TOUCHING_OPS = ("set_connector", "rename", "hide", "confirm")


def _summary(old: FlowNode, new: FlowNode) -> list[str]:
    parts: list[str] = []
    if old.title != new.title:
        parts.append(f'"{old.title}" is now "{new.title}"')
    old_model = old.op.model if old.op else None
    new_model = new.op.model if new.op else None
    if old_model != new_model:
        parts.append(f"model {old_model or 'none'} → {new_model or 'none'}")
    if old.connector != new.connector:
        parts.append(f"app {old.connector} → {new.connector}")
    if old.condition != new.condition and old.title == new.title:
        parts.append(f"condition {old.condition} → {new.condition}")
    if old.what != new.what and not parts:
        parts.append("what it does changed")
    return parts or ["details changed"]


def _same(old: FlowNode, new: FlowNode) -> bool:
    return all(getattr(old, f) == getattr(new, f) for f in CompareFields)


def _groups(added: list[str], edges: list[FlowEdge]) -> list[list[str]]:
    """Added blocks joined by lines form one change (a new route is one thing to accept, not three)."""
    left, groups = list(added), []
    while left:
        group, queue = [], [left.pop(0)]
        while queue:
            node = queue.pop()
            group.append(node)
            for e in edges:
                for a, b in ((e.source, e.target), (e.target, e.source)):
                    if a == node and b in left:
                        left.remove(b)
                        queue.append(b)
        groups.append(group)
    return groups


def diff(old: Flow, new: Flow, overrides: list[tuple[int, Override]], notes: Mapping[str, str]) -> list[dict[str, Any]]:
    old_nodes = {n.id: n for n in old.nodes}
    new_nodes = {n.id: n for n in new.nodes}
    touched: dict[str, list[Override]] = {}
    for _, o in overrides:
        if o.op in TOUCHING_OPS and o.node:
            touched.setdefault(o.node, []).append(o)
    changes: list[dict[str, Any]] = []

    def add(kind: str, title: str, nodes: list[str], node: FlowNode, **extra: Any) -> None:
        ev = next((e.ref for e in node.evidence if e.ref), "")
        changes.append({"id": f"c{len(changes) + 1}", "type": kind, "title": title, "nodes": nodes,
                        "detail": notes.get(nodes[0], ""), "evidence": ev, **extra})

    added = [n.id for n in new.nodes if n.id not in old_nodes]
    for group in _groups(added, new.edges):
        first = new_nodes[group[0]]
        more = f" (+{len(group) - 1} more)" if len(group) > 1 else ""
        add("add", f"New: {first.title}{more}", group, first)

    for node_id, new_node in new_nodes.items():
        old_node = old_nodes.get(node_id)
        if old_node is None or _same(old_node, new_node):
            continue
        first = _summary(old_node, new_node)[0]
        title = first if old_node.title != new_node.title else f"{new_node.title}: {first}"
        if node_id in touched:
            add("conflict", title, [node_id], new_node,
                choices=[["mine", "Keep your edit"], ["planner", "Use the Planner's"]])
        else:
            add("change", title, [node_id], new_node)

    for node_id, old_node in old_nodes.items():
        if node_id in new_nodes:
            continue
        if node_id in touched:
            add("conflict", f'Drop "{old_node.title}"', [node_id], old_node,
                choices=[["mine", "Keep it (yours)"], ["planner", "Drop it"]])
        else:
            add("remove", f'Drop "{old_node.title}"', [node_id], old_node)

    for _, o in overrides:
        if o.op == "add_node" and o.new_node is not None:
            changes.append({"id": f"c{len(changes) + 1}", "type": "kept", "title": f'"{o.new_node.title}" stays',
                            "nodes": [o.new_node.id], "evidence": "added by you",
                            "detail": "Your own step. The Planner never removes steps you added."})
    return changes


def default_take(changes: list[dict[str, Any]]) -> dict[str, bool | str]:
    return {c["id"]: ("mine" if c["type"] == "conflict" else True) for c in changes if c["type"] != "kept"}


def apply_choices(old: Flow, new: Flow, changes: list[dict[str, Any]],
                  take: Mapping[str, bool | str]) -> tuple[Flow, set[str]]:
    """The Planner version to accept, plus the blocks whose user edits should be dropped."""
    choice = {**default_take(changes), **take}
    old_nodes = {n.id: n for n in old.nodes}
    nodes = {n.id: n.model_copy(deep=True) for n in new.nodes}
    order = [n.id for n in new.nodes]
    edges = [e.model_copy(deep=True) for e in new.edges]
    drop_edits: set[str] = set()

    def restore(node_id: str) -> None:
        if node_id not in nodes:
            order.append(node_id)
        nodes[node_id] = old_nodes[node_id].model_copy(deep=True)
        have = {(e.source, e.target, e.kind) for e in edges}
        for e in old.edges:
            if node_id in (e.source, e.target) and (e.source, e.target, e.kind) not in have:
                edges.append(e.model_copy(deep=True))

    for c in changes:
        picked = choice.get(c["id"])
        if c["type"] == "add" and picked is False:
            for node_id in c["nodes"]:
                nodes.pop(node_id, None)
                order.remove(node_id)
        elif c["type"] in ("change", "remove") and picked is False:
            for node_id in c["nodes"]:
                restore(node_id)
        elif c["type"] == "conflict":
            node_id = c["nodes"][0]
            if picked == "planner":
                drop_edits.add(node_id)
            elif node_id not in nodes:   # kept a block the Planner wanted to drop
                restore(node_id)

    kept_edges = [e for e in edges if e.source in nodes and e.target in nodes]
    suggestions = [s for s in new.suggestions if s.node in nodes]
    return Flow(nodes=[nodes[i] for i in order if i in nodes], edges=kept_edges, suggestions=suggestions), drop_edits
