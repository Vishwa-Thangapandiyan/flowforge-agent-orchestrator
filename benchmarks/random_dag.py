"""Random DAG generator for the simulated track (D6). Owner: Person C.

Edges only go from an earlier to a later step in a hidden rank order, so every
graph is acyclic by construction; the declared order is shuffled afterwards so
the input is never already topologically sorted.

Every step is a `mock` step. Its duration is drawn from a per-type latency
distribution (real measurements from the real track when available, otherwise
the defaults below), then multiplied by `time_scale` so a benchmark of hundreds
of graphs finishes in minutes. Comparisons are ratios, so scaling doesn't change them.

Duplicate calls: with probability `dup_prob` a step reuses an earlier step's
call (same params, same duration) — like two branches fetching the same page.
All other steps get a unique "call" param, since identical mock params are
identical calls and the cache would merge them.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from flowforge.schema import Workflow

# (median ms, sigma of log) — lognormal, a standard fit for API latency
DEFAULT_LATENCY = {"llm": (2500.0, 0.6), "http": (600.0, 0.5), "mcp": (1500.0, 0.6)}
TYPE_MIX = {"llm": 0.6, "http": 0.3, "mcp": 0.1}


@dataclass
class LatencyModel:
    """Samples a step latency in ms for a step type."""

    samples: dict[str, list[float]] | None = None  # measured latencies from the real track

    @classmethod
    def load(cls, path: Path) -> LatencyModel:
        if path.exists():
            data = json.loads(path.read_text())
            return cls({t: v for t, v in data.items() if v})
        return cls()

    def sample(self, step_type: str, rng: random.Random) -> float:
        if self.samples and self.samples.get(step_type):
            return rng.choice(self.samples[step_type])
        median, sigma = DEFAULT_LATENCY[step_type]
        return rng.lognormvariate(math.log(median), sigma)


@dataclass
class GeneratedDAG:
    workflow: Workflow
    weights_ms: dict[str, float]  # scaled durations: the true weights for the lower bound


def generate(
    rng: random.Random,
    *,
    n_steps: int,
    edge_prob: float,
    max_parents: int = 4,
    k: int = 4,
    dup_prob: float = 0.1,
    latency: LatencyModel | None = None,
    time_scale: float = 0.01,
    wf_id: str = "random",
) -> GeneratedDAG:
    latency = latency or LatencyModel()
    ids = [f"s{i}" for i in range(n_steps)]
    types = rng.choices(list(TYPE_MIX), weights=list(TYPE_MIX.values()), k=n_steps)

    calls: list[tuple[str, float]] = []  # (call id, scaled duration) made so far
    steps, weights = [], {}
    for i, sid in enumerate(ids):
        candidates = ids[:i]
        parents = [p for p in candidates if rng.random() < edge_prob]
        if len(parents) > max_parents:
            parents = rng.sample(parents, max_parents)

        if calls and rng.random() < dup_prob:
            call, duration = rng.choice(calls)
        else:
            call, duration = f"c{i}", max(1.0, latency.sample(types[i], rng) * time_scale)
            calls.append((call, duration))
        weights[sid] = duration
        steps.append({
            "id": sid,
            "type": "mock",
            "depends_on": sorted(parents, key=ids.index),
            "params": {"duration_ms": round(duration, 3), "call": call},
            "description": f"simulated {types[i]} call",
        })

    rng.shuffle(steps)
    workflow = Workflow.model_validate({"id": wf_id, "max_concurrency": k, "steps": steps})
    return GeneratedDAG(workflow, weights)
