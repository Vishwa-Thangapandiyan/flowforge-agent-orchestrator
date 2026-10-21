"""The Planner interface (D17) and its two implementations.

`FixturePlanner` draws the hand-made Baby-care flow map, test data for the flow-map code: nothing hand-drawn
reaches the dashboard (D23). `ScanPlanner` scans a folder and draws its dependency map (D21). `CodeFlowPlanner` reads
the folder's Python and draws the order it calls those dependencies (D25). The last two are plain code, no LLM (D20).
All return the same `Draft`, so versions, re-checks and edits work alike.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from flowforge.flowmap import fixture
from flowforge.flowmap.models import CALL_KINDS, Analysis, AnalysisStage, Evidence, Flow, FlowEdge, FlowNode, Op, Trace
from flowforge.scan import ScanResult, scan


@dataclass
class Draft:
    flow: Flow
    trace: Trace | None
    analysis: Analysis
    fact_sheet_hash: str


class NoFlow(Exception):
    """There is nothing to draw, and the message says why (D25: "Flow order needs Python for now")."""


class Planner(Protocol):
    def analyze(self, round: int) -> Draft:
        """Draw the map. `round` is 0 for the first map and counts up with every re-check."""
        ...


def fact_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


class FixturePlanner:
    """The Baby-care shop, for tests (D23). Round 0 is the first map; any later round is the re-check."""

    def analyze(self, round: int) -> Draft:
        recheck = round > 0
        flow = fixture.flow_v2() if recheck else fixture.flow_v1()
        facts = {"repo": "you/baby-care-shop", "commit": "b7e9d21" if recheck else "a1b2c3f"}
        return Draft(flow=flow, trace=fixture.trace(), analysis=fixture.analysis(recheck=recheck),
                     fact_sheet_hash=fact_hash(facts))


APP_ID, TOOLS_ID = "app", "tools"


class ScanPlanner:
    """A real repo (D21): scan the folder, draw one block per dependency off the app (or your coding tools)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def analyze(self, round: int) -> Draft:   # every round scans the folder as it is now
        return draft_from_scan(scan(self.root))


def draft_from_scan(result: ScanResult) -> Draft:
    deps = result.dependencies
    nodes = [FlowNode(id=APP_ID, kind="start", title=result.root[:80], what="Your app: the folder that was scanned.",
                      evidence=[Evidence(type="code", text=f"{result.files_scanned} files read.")])]
    if any(d.scope == "dev_tool" for d in deps):
        nodes.append(FlowNode(id=TOOLS_ID, kind="start", title="Your coding tools",
                              what="MCP servers your coding tools use, not your app.",
                              evidence=[Evidence(type="code", text="In an MCP config file the app never reads.")]))
    ids = {d.id for d in deps}
    edges = []
    for d in deps:
        nodes.append(FlowNode(
            id=d.id, kind=d.kind, title=d.name[:80], what=(d.target or "")[:300], catalog=d.catalog,
            op=Op(model=d.model) if d.model else None, status=d.status,
            evidence=[Evidence(type="code", ref=e.ref, text=e.text, first_line=e.first_line, lines=e.lines,
                               highlight=e.highlight) for e in d.evidence]))
        source = d.via if d.via in ids else TOOLS_ID if d.scope == "dev_tool" else APP_ID
        edges.append(FlowEdge(id=f"{source}__{d.id}"[:64], source=source, target=d.id))
    confirmed = sum(d.status == "confirmed" for d in deps)
    unconfirmed = len(deps) - confirmed
    analysis = Analysis(
        stages=[
            AnalysisStage(title="Read your code", done=f"{result.files_scanned} files read, nothing run or sent"),
            AnalysisStage(title="Found dependencies", done=f"{len(deps)} found"),
            AnalysisStage(title="Checked the evidence", done=f"{confirmed} confirmed, {unconfirmed} unconfirmed"),
        ],
        files=sorted({e.ref.rsplit(":", 1)[0] for d in deps for e in d.evidence})[:200],
        scan=result.model_dump(mode="json"))
    facts = [(d.id, d.kind, d.target, d.status, [e.ref for e in d.evidence]) for d in deps]
    return Draft(flow=Flow(kind="dependencies", nodes=nodes, edges=edges), trace=None, analysis=analysis,
                 fact_sheet_hash=fact_hash(facts))


class CodeFlowPlanner:
    """A real repo's flow (D25): read its Python, draw the order its entry points call their dependencies, weighted
    by the latest checks (D24). `latencies` is asked each time, so a re-scan picks up newer checks."""

    def __init__(self, root: str | Path, latencies: Callable[[], dict[str, float]] = dict):
        self.root = Path(root)
        self.latencies = latencies

    def analyze(self, round: int) -> Draft:
        from flowforge.flow import flow_of  # flow/ builds on scan/ and flowmap/; imported here to keep them apart

        result = flow_of(self.root, self.latencies())
        if result.flow is None:
            raise NoFlow(result.message or "No flow to draw.")
        flow = result.flow
        steps = [n for n in flow.nodes if n.kind in CALL_KINDS]
        measured = sum(n.estimate_source == "measured" for n in steps)
        analysis = Analysis(
            stages=[
                AnalysisStage(title="Read your Python", done=f"{len(result.entries)} entry point"
                              f"{'s' if len(result.entries) != 1 else ''}, nothing run or sent"),
                AnalysisStage(title="Followed the calls", done=f"{len(steps)} calls, "
                              f"{sum(n.kind == 'decision' for n in flow.nodes)} decisions"),
                AnalysisStage(title="Weighed them",
                              done=f"{measured} measured by checks, {len(steps) - measured} estimated"),
            ],
            files=sorted({n.evidence[0].ref.rsplit(":", 1)[0] for n in flow.nodes if n.evidence and n.evidence[0].ref}))
        facts = [(n.id, n.kind, n.condition, [e.ref for e in n.evidence]) for n in flow.nodes] + \
            [(e.source, e.target, e.when) for e in flow.edges]
        return Draft(flow=flow, trace=None, analysis=analysis, fact_sheet_hash=fact_hash(facts))
