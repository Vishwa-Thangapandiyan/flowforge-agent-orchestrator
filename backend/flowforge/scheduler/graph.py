"""DAG construction, topological sort, cycle detection (D7). Owner: Person A."""

from __future__ import annotations

import heapq
from collections import deque
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
    nodes = [s.id for s in workflow.steps]
    parents = {s.id: list(dict.fromkeys(s.depends_on)) for s in workflow.steps}  # dedupe, keep order
    children: dict[str, list[str]] = {n: [] for n in nodes}
    for child in nodes:
        for parent in parents[child]:
            children[parent].append(child)

    dag = DAG(nodes=nodes, parents=parents, children=children)
    topological_order(dag)  # raises CycleError
    return dag


def topological_order(dag: DAG) -> list[str]:
    """Kahn's algorithm. Ties are broken by original step order (a min-heap on the
    step's index), so the output is deterministic: O((V + E) log V).

    If fewer than V nodes come out, find and raise the actual cycle.
    """
    index = {n: i for i, n in enumerate(dag.nodes)}
    indegree = {n: len(dag.parents[n]) for n in dag.nodes}
    ready = [index[n] for n in dag.nodes if indegree[n] == 0]
    heapq.heapify(ready)

    order: list[str] = []
    while ready:
        node = dag.nodes[heapq.heappop(ready)]
        order.append(node)
        for child in dag.children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, index[child])

    if len(order) < len(dag.nodes):
        leftover = [n for n in dag.nodes if indegree[n] > 0]
        raise CycleError(_find_cycle(dag, set(leftover), leftover[0]))
    return order


def _find_cycle(dag: DAG, leftover: set[str], start: str) -> list[str]:
    """Every node Kahn's left behind still has an unprocessed parent, which is itself
    left over. So walking parent links from any leftover node stays inside the leftovers
    and must eventually revisit a node — that repeat closes a cycle.
    """
    position: dict[str, int] = {}
    walk: list[str] = []
    node = start
    while node not in position:
        position[node] = len(walk)
        walk.append(node)
        node = next(p for p in dag.parents[node] if p in leftover)
    # walk[position[node]:] follows child → parent; reverse it to read in execution order
    cycle = walk[position[node]:][::-1]
    return cycle + [cycle[0]]


def levels(dag: DAG) -> list[list[str]]:
    """BFS layers: level 0 = no parents, level i = longest parent chain of length i.

    Used by benchmark strategy S2 (level-by-level with barriers).
    Within a level, steps keep their original order.
    """
    level: dict[str, int] = {}
    for node in topological_order(dag):
        level[node] = 1 + max((level[p] for p in dag.parents[node]), default=-1)

    layers: list[list[str]] = [[] for _ in range(max(level.values(), default=-1) + 1)]
    for node in dag.nodes:
        layers[level[node]].append(node)
    return layers


def descendants(dag: DAG, step_id: str) -> set[str]:
    """Every step reachable from step_id — these get `skipped` when it fails."""
    seen: set[str] = set()
    queue = deque(dag.children[step_id])
    while queue:
        node = queue.popleft()
        if node not in seen:
            seen.add(node)
            queue.extend(dag.children[node])
    return seen
