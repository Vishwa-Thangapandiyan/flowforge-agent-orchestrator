"""The Planner interface (D17) and its two implementations.

`FixturePlanner` draws the example Baby-care flow map. `ScanPlanner` scans a folder and draws its dependency
map (D21): plain code, no LLM (D20). Both return the same `Draft`, so versions, re-checks and edits work alike.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from flowforge.flowmap import fixture
from flowforge.flowmap.models import Analysis, AnalysisStage, Evidence, Flow, FlowEdge, FlowNode, Op, Trace
from flowforge.scan import ScanResult, scan


@dataclass
class Draft:
    flow: Flow
    trace: Trace | None
    analysis: Analysis
    fact_sheet_hash: str


class Planner(Protocol):
    def analyze(self, round: int) -> Draft:
        """Draw the map. `round` is 0 for the first map and counts up with every re-check."""
        ...


def fact_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


class FixturePlanner:
    """Example mode: the Baby-care shop. Round 0 is the first map; any later round is the re-check."""

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
