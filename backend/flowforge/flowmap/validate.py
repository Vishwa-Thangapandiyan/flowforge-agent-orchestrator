"""Checks on a flow map and the gating policy (D17, D14).

`check()` runs on the Planner's output and again on the merged map after the user's edits, so
no edit can open a path around a gate. Code decides what is side-effecting; the Planner can add
gates but never remove one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from flowforge.connectors.models import Connector
from flowforge.flowmap.models import CALL_KINDS, CONNECTOR_TYPE, Evidence, Flow, FlowEdge, FlowNode
from flowforge.scheduler.critical_path import critical_path
from flowforge.scheduler.graph import DAG, CycleError, topological_order

# rough per-kind estimates (ms) when the Planner gives none (extends D1)
DEFAULT_MS = {"llm": 2000.0, "api": 300.0, "mcp": 500.0, "local": 1000.0, "code": 50.0}
# blocks that need evidence of their own; fork/join/gate/end get their meaning from the lines around them
NEEDS_EVIDENCE = CALL_KINDS | {"code", "decision", "start"}
POLICY_TEXT = "Side effects always wait for you (D14). Added by code, so no edit can remove it."


class FlowError(ValueError):
    """The map is structurally wrong. The message is one plain sentence naming the block."""


def side_effecting(node: FlowNode) -> bool:
    """D14 list, decided by code: non-GET HTTP, MCP tools not marked read-only, every local command.

    D17 refinement: a GET to a payment API reads; only calls that move money or send are gated.
    """
    op = node.op
    if node.kind == "local":
        return True
    if node.kind == "mcp":
        return not (op is not None and op.read_only is True)
    if node.kind == "api":
        return op is None or op.method not in ("GET", "HEAD")
    return False


def _dag(flow: Flow, kinds: set[str]) -> DAG:
    nodes = [n.id for n in flow.nodes]
    parents: dict[str, list[str]] = {n: [] for n in nodes}
    children: dict[str, list[str]] = {n: [] for n in nodes}
    for e in flow.edges:
        if e.kind in kinds and e.source not in parents[e.target]:
            parents[e.target].append(e.source)
            children[e.source].append(e.target)
    return DAG(nodes=nodes, parents=parents, children=children)


def check(flow: Flow, connectors: Mapping[str, Connector], strict: bool = True) -> Flow:
    """A checked copy: statuses and side effects set, unconfirmed lines marked, policy gates inserted.

    Raises FlowError for a loop, a call with no app, an unknown app, a type mismatch or a decision
    without two labelled branches. With `strict=False` (drawing the map) an app problem marks the
    block unconfirmed instead, so deleting a connector never breaks the page.
    """
    flow = flow.model_copy(deep=True)
    try:
        topological_order(_dag(flow, {"flow", "branch", "fallback", "unconfirmed"}))
    except CycleError as err:
        raise FlowError(f"the map has a loop: {' → '.join(err.cycle)}") from None

    for node in flow.nodes:
        if node.kind in NEEDS_EVIDENCE and node.status == "confirmed" and node.added_by != "user" \
                and not any(ev.confirms for ev in node.evidence):
            node.status = "unconfirmed"
        if node.kind in CALL_KINDS:
            try:
                _check_connector(node, connectors)
            except FlowError as err:
                if strict:
                    raise
                node.status = "unconfirmed"
                node.evidence = [*node.evidence, Evidence(type="missing", text=str(err).capitalize() + ".")]
        node.side_effect = side_effecting(node)
        if node.kind == "decision":
            whens = [e.when for e in flow.edges if e.source == node.id and e.kind == "branch"]
            if len(set(whens)) < 2:
                raise FlowError(f"decision '{node.title}' needs two labelled branches (for example yes and no)")

    unconfirmed = {n.id for n in flow.nodes if n.status == "unconfirmed"}
    for e in flow.edges:
        if e.kind != "retry" and e.target in unconfirmed:
            e.kind = "unconfirmed"
        elif e.kind == "unconfirmed":
            e.kind = "flow"

    _insert_gates(flow)
    return flow


def _check_connector(node: FlowNode, connectors: Mapping[str, Connector]) -> None:
    if not node.connector:
        raise FlowError(f"block '{node.title}' is an app call but names no app")
    connector = connectors.get(node.connector)
    if connector is None:
        if node.status == "unconfirmed":
            return  # a hint may name an app nobody has connected yet
        raise FlowError(f"block '{node.title}' uses '{node.connector}', which is not connected")
    want = CONNECTOR_TYPE[node.kind]
    if connector.type != want:
        raise FlowError(f"block '{node.title}' is a {node.kind} call but '{node.connector}' is a {connector.type} app")


def _insert_gates(flow: Flow) -> None:
    """Every confirmed side-effecting block gets a gate in front of it unless every way in is a gate."""
    kinds = {n.id: n.kind for n in flow.nodes}
    for node in list(flow.nodes):
        if not node.side_effect or node.status != "confirmed":
            continue
        incoming = [e for e in flow.edges if e.target == node.id and e.kind not in ("retry", "unconfirmed")]
        if incoming and all(kinds[e.source] == "gate" for e in incoming):
            continue
        gate_id = _free_id({n.id for n in flow.nodes}, f"gate_{node.id}")
        gate = FlowNode(id=gate_id, kind="gate", title=f"Approve: {node.title}"[:80], added_by="policy",
                        what="This step changes something outside the app, so it waits for you.",
                        evidence=[Evidence(type="policy", text=POLICY_TEXT)])
        flow.nodes.insert(flow.nodes.index(node), gate)
        kinds[gate_id] = "gate"
        for e in incoming:
            e.target = gate_id
        flow.edges.append(FlowEdge(id=_free_id({e.id for e in flow.edges}, f"{gate_id}_to_{node.id}")[:64],
                                   source=gate_id, target=node.id))


def _free_id(taken: set[str], base: str) -> str:
    base = base[:60]
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


@dataclass
class Critical:
    path: list[str] = field(default_factory=list)
    length_ms: float = 0.0
    bottleneck: str | None = None   # the slowest block on the path


def weight(node: FlowNode) -> float:
    if node.estimate_ms is not None:
        return node.estimate_ms
    return DEFAULT_MS.get(node.kind, 0.0)


def critical(flow: Flow) -> Critical:
    """The longest expected chain (D1, D5) through the app's own flow: normal and branch lines only.
    Fallbacks, retries, unconfirmed blocks and steps the user added are not the expected path.
    Gates weigh 0, as people are not a resource."""
    keep = {n.id for n in flow.nodes if n.status == "confirmed" and n.added_by != "user"}
    lines = [e for e in flow.edges if e.kind in ("flow", "branch") and e.source in keep and e.target in keep]
    # only blocks reachable from a start along normal lines (a fallback-only block is not the expected path)
    roots = [n.id for n in flow.nodes if n.id in keep and n.kind == "start"] or \
        [i for i in keep if not any(e.target == i for e in lines)]
    reach, queue = set(roots), list(roots)
    while queue:
        here = queue.pop()
        for e in lines:
            if e.source == here and e.target not in reach:
                reach.add(e.target)
                queue.append(e.target)
    sub = Flow(nodes=[n for n in flow.nodes if n.id in reach],
               edges=[e for e in lines if e.source in reach and e.target in reach])
    if not sub.nodes:
        return Critical()
    weights = {n.id: 0.0 if n.kind == "gate" else weight(n) for n in sub.nodes}
    dag = _dag(sub, {"flow", "branch"})
    cp = critical_path(dag, weights)
    path = list(cp.path)
    while path:  # carry on through zero-time blocks (an end, a join) so the chain reaches its end
        nxt = next((c for c in dag.children[path[-1]] if weights[c] == 0 and c not in path), None)
        if nxt is None:
            break
        path.append(nxt)
    bottleneck = max(path, key=lambda i: weights[i]) if path else None
    return Critical(path=path, length_ms=cp.length_ms, bottleneck=bottleneck)
