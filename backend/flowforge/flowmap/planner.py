"""The Planner interface (D17). Phase 3 ships one implementation: the example-mode fixture.

The real Planner (Phase 5) reads the repo, runs the app in test mode, redacts the facts and asks a
background LLM for the same `Draft`. Its engine is never shown to the user.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from flowforge.flowmap import fixture
from flowforge.flowmap.models import Analysis, Flow, Trace


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
