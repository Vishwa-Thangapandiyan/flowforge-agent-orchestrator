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

A map is a `flow` (the order the app runs in, D17) or `dependencies` (what the app uses, from a scan, D21).
A flow read from code (`source="code"`, D25) carries no gates and no connected apps; its `advice` says which calls
could run together.
On a dependency map an app-call block is a dependency: it needs no connected app, gets no gate and no
critical path, and `catalog` names a known service for its tile.
"""

from __future__ import annotations

from typing import Any, Literal

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
    catalog: str | None = None  # dependency maps: a known service's id, for its tile (D21)
    repeats: bool = False       # flows read from code: the call sits in a loop (D25)
    estimate_source: Literal["measured", "estimate"] | None = None   # where `estimate_ms` came from (D25)
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


class Change(_Model):
    """The advice written out (D27): lines as they are and as they would be, masked like evidence. Text to copy,
    never applied. `by_hand`: calls of the same advice in another block, each with where it is and why."""

    path: str
    first_line: int = Field(ge=1)
    before: list[str]
    after: list[str]
    saved_ms: float = Field(ge=0)
    by_hand: list[str] = Field(default_factory=list)
    needs_import: bool = False
    import_text: str | None = None   # the import to add for the change, when the file lacks it (D32)


class Action(_Model):
    """One entry point of a flow read from code, as the action picker shows it (D33): its calls one after another
    as written, as early as inputs allow, and the chain that sets that time."""

    id: str                        # its start block
    title: str
    written_ms: float = Field(ge=0)
    could_ms: float = Field(ge=0)
    path: list[str] = Field(default_factory=list)
    calls: int = 0
    # its calls as written, in groups: one call, or calls the code already runs together (count once, at the
    # slowest). Kept so "as written" can be recomputed from what is still on the map after edits.
    parts: list[list[str]] = Field(default_factory=list)


class Advice(_Model):
    """Calls that could start together (D25): awaited one after another, and none uses another's result.
    `saved_ms` is what running them together would save, from the blocks' weights. `change` writes it out when plain
    code can do so safely; `prompt` hands it to a coding agent (D27)."""

    nodes: list[str] = Field(min_length=2)
    refs: list[str]
    text: str = Field(max_length=300)
    saved_ms: float = Field(ge=0)
    caveat: str | None = Field(default=None, max_length=300)
    change: Change | None = None
    prompt: str = Field(default="", max_length=3000)


class Flow(_Model):
    kind: Literal["flow", "dependencies"] = "flow"
    source: Literal["planner", "code"] = "planner"   # code: read from the repo's own code (D25)
    nodes: list[FlowNode]
    edges: list[FlowEdge] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    advice: list[Advice] = Field(default_factory=list)
    written_ms: float | None = None   # code flows: every call one after another, as the code is written (D25)
    patterns: list[str] = Field(default_factory=list)   # code flows: languages read by patterns, less exact (D32)
    actions: list[Action] = Field(default_factory=list)   # code flows: one per entry point, slowest first (D33)
    reader: int = 0   # the reader that made it (flowmap.planner.READER); an older one is read again on start (D35)

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
        for a in self.advice:
            missing = [n for n in a.nodes if n not in known]
            if missing:
                raise ValueError(f"advice for unknown block '{missing[0]}'")
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
    scan: dict[str, Any] | None = None   # dependency maps: the full ScanResult, for checks later (D21)


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
