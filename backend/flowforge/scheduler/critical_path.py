"""Critical path + bottom levels via DP over the DAG (D1, D5). Owner: Person A."""

from __future__ import annotations

from dataclasses import dataclass

from flowforge.scheduler.graph import DAG, topological_order


@dataclass
class CriticalPath:
    path: list[str]      # bottleneck chain, source → sink
    length_ms: float     # sum of weights along it


def critical_path(dag: DAG, weights: dict[str, float]) -> CriticalPath:
    """Longest weighted path. DP in topological order:
    finish[v] = weights[v] + max(finish[p] for p in parents[v], default 0);
    keep the argmax parent to reconstruct the path. O(V + E).

    Ties go to the earlier-declared parent / earlier sink, so the answer is deterministic.
    """
    order = topological_order(dag)
    finish: dict[str, float] = {}
    via: dict[str, str | None] = {}
    for v in order:
        best = None
        for p in dag.parents[v]:
            if best is None or finish[p] > finish[best]:
                best = p
        via[v] = best
        finish[v] = weights[v] + (finish[best] if best is not None else 0)

    end = order[0]
    for v in order:
        if finish[v] > finish[end]:
            end = v

    path: list[str] = []
    node: str | None = end
    while node is not None:
        path.append(node)
        node = via[node]
    return CriticalPath(path=path[::-1], length_ms=finish[end])


def bottom_levels(dag: DAG, weights: dict[str, float]) -> dict[str, float]:
    """Scheduling priority (HLFET). DP in *reverse* topological order:
    bl[v] = weights[v] + max(bl[c] for c in children[v], default 0).

    max(bl) equals the critical path length — the step with the highest
    bottom level heads the longest remaining chain, so it should start first.
    """
    bl: dict[str, float] = {}
    for v in reversed(topological_order(dag)):
        bl[v] = weights[v] + max((bl[c] for c in dag.children[v]), default=0)
    return bl


def lower_bound_ms(dag: DAG, weights: dict[str, float], k: int) -> float:
    """max(critical path length, total work / k) — no schedule on k slots can beat this:
    the critical chain must run one step after another, and k slots can do at most
    k units of work per unit of time.
    """
    return max(critical_path(dag, weights).length_ms, sum(weights[v] for v in dag.nodes) / k)
