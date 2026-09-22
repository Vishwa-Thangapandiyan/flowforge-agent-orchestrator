"""DAG construction, topological sort, cycle detection (D7). Owner: Person A."""

from __future__ import annotations

from dataclasses import dataclass, field

from flowforge.schema import Workflow


class CycleError(ValueError):
    def __init__(self, cycle: list[str]):
        # cycle is closed: ["a", "b", "c", "a"]
        super().__init__("cycle: " + " → ".join(cycle))
        self.cycle = cycle


@dataclass
class DAG:
    nodes: list[str]
    parents: dict[str, list[str]] = field(default_factory=dict)   # step -> its depends_on
    children: dict[str, list[str]] = field(default_factory=dict)  # step -> steps depending on it


def build_dag(workflow: Workflow) -> DAG:
    """Adjacency lists from `depends_on`. Raise CycleError if the graph is not acyclic."""
    raise NotImplementedError


def topological_order(dag: DAG) -> list[str]:
    """Kahn's algorithm, O(V + E). Break ties by original step order so output is deterministic.

    If fewer than V nodes come out, find and raise the actual cycle (DFS over the leftovers).
    """
    raise NotImplementedError


def levels(dag: DAG) -> list[list[str]]:
    """BFS layers: level 0 = no parents, level i = longest parent chain of length i.

    Used by benchmark strategy S2 (level-by-level with barriers).
    """
    raise NotImplementedError


def descendants(dag: DAG, step_id: str) -> set[str]:
    """Every step reachable from step_id — these get `skipped` when it fails."""
    raise NotImplementedError
