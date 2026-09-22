"""Critical path + bottom levels via DP over the DAG (D1, D5). Owner: Person A."""

from __future__ import annotations

from dataclasses import dataclass

from flowforge.scheduler.graph import DAG


@dataclass
class CriticalPath:
    path: list[str]      # bottleneck chain, source → sink
    length_ms: float     # sum of weights along it


def critical_path(dag: DAG, weights: dict[str, float]) -> CriticalPath:
    """Longest weighted path. DP in topological order:
    finish[v] = weights[v] + max(finish[p] for p in parents[v], default 0);
    keep the argmax parent to reconstruct the path. O(V + E).
    """
    raise NotImplementedError


def bottom_levels(dag: DAG, weights: dict[str, float]) -> dict[str, float]:
    """Scheduling priority (HLFET). DP in *reverse* topological order:
    bl[v] = weights[v] + max(bl[c] for c in children[v], default 0).
    """
    raise NotImplementedError


def lower_bound_ms(dag: DAG, weights: dict[str, float], k: int) -> float:
    """max(critical path length, total work / k) — no schedule on k slots can beat this."""
    raise NotImplementedError
