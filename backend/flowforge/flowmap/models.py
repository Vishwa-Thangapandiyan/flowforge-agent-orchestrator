"""Flow JSON (D17). What the Planner returns and what the map draws.

Blocks (`FlowNode.kind`):
  start, end              where a flow begins (route, webhook, schedule) and stops
  llm, api, mcp, local    one call to a connected app (`connector` names it)
  code                    the app's own code, no outside call
  decision                one branch is taken; its lines carry `when`
  fork, join              run together / wait for all
  gate                    a person approves; added by the Planner or by code (`added_by="policy"`)

Lines (`FlowEdge.kind`): flow, branch (with `when`), fallback (taken when the source fails),
retry (a self-loop: the call is tried again), unconfirmed (leads to a block with no evidence).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeKind = Literal["start", "end", "llm", "api", "mcp", "local", "code", "decision", "fork", "join", "gate"]
EdgeKind = Literal["flow", "branch", "fallback", "retry", "unconfirmed"]

CALL_KINDS = {"llm", "api", "mcp", "local"}
# block kind -> the connector type it must use (D10)
CONNECTOR_TYPE = {"llm": "llm", "api": "http", "mcp": "mcp", "local": "local"}

_ID = r"^[A-Za-z0-9_\-]{1,64}$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_Model):
    """Why a block is on the map. `code` and `trace` confirm a block; `env_name` is only a hint."""

    type: Literal["code", "trace", "policy", "env_name", "user", "missing"]
    ref: str | None = Field(default=None, max_length=200)    # "services/risk.py:44"
    text: str | None = Field(default=None, max_length=300)   # one short sentence
    first_line: int | None = None                            # code excerpt: number of its first line
    lines: list[str] = Field(default_factory=list, max_length=12)
    highlight: int | None = None                             # the line the ref points at

    @property
    def confirms(self) -> bool:
        return self.type in ("code", "trace", "user", "policy")


class Op(_Model):
    """What a call does. Gating reads `method` (HTTP) and `read_only` (MCP), never the Planner's opinion."""

    model: str | None = None
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"] | None = None
    path: str | None = None
    tool: str | None = None
    read_only: bool | None = None


class FlowNode(_Model):
    id: str = Field(pattern=_ID)
    kind: NodeKind
    title: str = Field(min_length=1, max_length=80)
    what: str = Field(default="", max_length=300)
    connector: str | None = None
    op: Op | None = None
    condition: str | None = Field(default=None, max_length=200)
    estimate_ms: float | None = Field(default=None, ge=0)
    status: Literal["confirmed", "unconfirmed"] = "confirmed"
    added_by: Literal["planner", "policy", "user"] = "planner"
    side_effect: bool = False   # set by validation, never trusted from input
    evidence: list[Evidence] = Field(default_factory=list)


class FlowEdge(_Model):
    id: str = Field(pattern=_ID)
    source: str
    target: str
    kind: EdgeKind = "flow"
    when: str | None = Field(default=None, max_length=24)    # branch label: "yes", "no"
    max: int | None = Field(default=None, ge=1, le=10)        # retry: attempts
    on: str | None = Field(default=None, max_length=60)       # retry/fallback: when it happens
    label: str | None = Field(default=None, max_length=40)


class Suggestion(_Model):
    """A better fit the Planner found while running the app (shown as a tip on the block)."""

    node: str
    connector: str
    text: str = Field(max_length=300)


class Flow(_Model):
    nodes: list[FlowNode]
    edges: list[FlowEdge] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structure(self) -> Flow:
        ids = [n.id for n in self.nodes]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate block id: {', '.join(dupes)}")
        edge_ids = [e.id for e in self.edges]
        dupes = sorted({i for i in edge_ids if edge_ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate line id: {', '.join(dupes)}")
        known = set(ids)
        for e in self.edges:
            for end in (e.source, e.target):
                if end not in known:
                    raise ValueError(f"line '{e.id}' points at unknown block '{end}'")
            if e.kind == "retry" and e.source != e.target:
                raise ValueError(f"retry line '{e.id}' must loop back to the same block")
            if e.kind != "retry" and e.source == e.target:
                raise ValueError(f"line '{e.id}' loops back to '{e.source}'; only retry lines may")
            if e.kind == "branch" and not e.when:
                raise ValueError(f"branch line '{e.id}' needs `when` (for example yes or no)")
        for s in self.suggestions:
            if s.node not in known:
                raise ValueError(f"suggestion for unknown block '{s.node}'")
        return self

    def node(self, node_id: str) -> FlowNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)


class TraceStep(_Model):
    """One block in a recorded test run. Times are offsets from the start of the run."""

    node: str
    start_ms: float = Field(ge=0)
    duration_ms: float = Field(ge=0)
    outcome: Literal["ok", "failed", "cached", "waiting"]
    answered_by: str | None = None
    note: str | None = Field(default=None, max_length=120)
    attempts: int = Field(default=1, ge=1)
    tokens: int = Field(default=0, ge=0)


class Trace(_Model):
    """A traced test order, replayed on the map (D17). `branches` says which way each decision went."""

    label: str = Field(max_length=80)
    steps: list[TraceStep]
    branches: dict[str, str] = Field(default_factory=dict)
    calls: int = 0
    cached: int = 0


class NodeStats(_Model):
    p50_ms: float | None = None
    summary: str = ""
    history: list[dict[str, float | bool]] = Field(default_factory=list)  # [{"ms": 2100, "ok": true}]


class AnalysisStage(_Model):
    title: str
    done: str
    doing: str = ""
    duration_ms: float = 2000


class Analysis(_Model):
    """How the Planner drew the map: its stages, a short log and the counts. Names only, never values."""

    stages: list[AnalysisStage]
    log: list[tuple[float, str, str]] = Field(default_factory=list)   # (at_ms, kind, text)
    files: list[str] = Field(default_factory=list)
    calls: list[dict[str, str | int | bool]] = Field(default_factory=list)
    dropped: list[dict[str, str]] = Field(default_factory=list)       # [{"title", "reason"}]
    stats: dict[str, NodeStats] = Field(default_factory=dict)
    notes: dict[str, str] = Field(default_factory=dict)               # block id -> why it changed (re-check)
    positions: dict[str, tuple[float, float]] = Field(default_factory=dict)  # optional starting layout


class Override(_Model):
    """One edit on top of the Planner's version (D17). It never touches the user's code."""

    op: Literal["set_connector", "rename", "hide", "confirm", "add_node", "add_edge"]
    node: str | None = Field(default=None, pattern=_ID)
    connector: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=80)
    new_node: FlowNode | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _fields(self) -> Override:
        need = {"set_connector": ("node", "connector"), "rename": ("node", "title"), "hide": ("node",),
                "confirm": ("node",), "add_node": ("new_node",), "add_edge": ("node", "source")}[self.op]
        missing = [f for f in need if getattr(self, f) in (None, "")]
        if missing:
            raise ValueError(f"{self.op} needs {', '.join(missing)}")
        return self
