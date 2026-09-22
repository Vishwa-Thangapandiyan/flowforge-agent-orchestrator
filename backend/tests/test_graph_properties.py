"""Property tests for graph.py on random DAGs (hypothesis)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from flowforge.schema import Workflow
from flowforge.scheduler import graph


@st.composite
def random_dags(draw, max_steps: int = 25):
    """Edges only go from a lower to a higher *rank*, so the graph is acyclic;
    the declared step order is then shuffled so the input isn't already sorted."""
    n = draw(st.integers(1, max_steps))
    edges = {
        f"s{j}": sorted(draw(st.sets(st.sampled_from([f"s{i}" for i in range(j)]), max_size=4)) if j else [])
        for j in range(n)
    }
    ids = draw(st.permutations(list(edges)))
    return {sid: edges[sid] for sid in ids}


def mk(edges):
    return Workflow.model_validate(
        {"id": "p", "steps": [{"id": s, "type": "mock", "depends_on": d} for s, d in edges.items()]}
    )


def closure(edges, start):
    children = {s: [c for c, ds in edges.items() if s in ds] for s in edges}
    seen, stack = set(), list(children[start])
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(children[node])
    return seen


@settings(max_examples=200)
@given(random_dags())
def test_order_is_a_permutation_respecting_every_edge(edges):
    order = graph.topological_order(graph.build_dag(mk(edges)))
    assert sorted(order) == sorted(edges)
    pos = {s: i for i, s in enumerate(order)}
    for child, parents in edges.items():
        for p in parents:
            assert pos[p] < pos[child]


@settings(max_examples=200)
@given(random_dags())
def test_levels_are_longest_chain_depths(edges):
    layers = graph.levels(graph.build_dag(mk(edges)))
    level = {s: i for i, layer in enumerate(layers) for s in layer}
    assert sorted(level) == sorted(edges) and all(layers)
    for child, parents in edges.items():
        assert level[child] == (1 + max(level[p] for p in parents) if parents else 0)


@settings(max_examples=100)
@given(random_dags(), st.data())
def test_descendants_match_brute_force(edges, data):
    start = data.draw(st.sampled_from(list(edges)))
    assert graph.descendants(graph.build_dag(mk(edges)), start) == closure(edges, start)


@settings(max_examples=200)
@given(random_dags(), st.data())
def test_back_edge_yields_a_real_cycle(edges, data):
    # make an ancestor depend on one of its descendants → guaranteed cycle
    candidates = [(s, d) for s in edges for d in closure(edges, s)]
    if not candidates:
        return
    ancestor, desc = data.draw(st.sampled_from(candidates))
    cyclic = {**edges, ancestor: edges[ancestor] + [desc]}  # ancestor now also depends on its descendant
    wf = mk(cyclic)
    with pytest.raises(graph.CycleError) as exc:
        graph.build_dag(wf)
    cycle = exc.value.cycle
    assert len(cycle) >= 3 and cycle[0] == cycle[-1]
    assert len(set(cycle[:-1])) == len(cycle) - 1  # simple cycle, no repeats
    for parent, child in zip(cycle, cycle[1:]):
        assert parent in cyclic[child]
