"""Property tests: the DP critical path matches brute-force longest path on small random DAGs."""

from hypothesis import given, settings
from hypothesis import strategies as st

from flowforge.scheduler import critical_path as cp
from flowforge.scheduler import graph

from test_graph_properties import mk, random_dags


def brute_force_longest(edges, weights):
    """Try every path by DFS from every step — exponential, fine for ≤ 10 steps."""
    children = {s: [c for c, ds in edges.items() if s in ds] for s in edges}
    best = 0.0

    def dfs(node, total):
        nonlocal best
        total += weights[node]
        best = max(best, total)
        for c in children[node]:
            dfs(c, total)

    for s in edges:
        dfs(s, 0.0)
    return best


@st.composite
def weighted_dags(draw):
    edges = draw(random_dags(max_steps=10))
    weights = {s: float(draw(st.integers(1, 1000))) for s in edges}
    return edges, weights


@settings(max_examples=300)
@given(weighted_dags())
def test_dp_matches_brute_force(case):
    edges, weights = case
    dag = graph.build_dag(mk(edges))
    result = cp.critical_path(dag, weights)
    assert result.length_ms == brute_force_longest(edges, weights)
    # the reported path is a real dependency chain whose weights add up
    for parent, child in zip(result.path, result.path[1:]):
        assert parent in edges[child]
    assert sum(weights[s] for s in result.path) == result.length_ms


@settings(max_examples=300)
@given(weighted_dags(), st.integers(1, 8))
def test_bottom_levels_and_lower_bound(case, k):
    edges, weights = case
    dag = graph.build_dag(mk(edges))
    bl = cp.bottom_levels(dag, weights)
    length = cp.critical_path(dag, weights).length_ms
    assert max(bl.values()) == length
    for child, parents in edges.items():
        for p in parents:
            assert bl[p] >= weights[p] + bl[child]  # a parent always outranks its children
    assert cp.lower_bound_ms(dag, weights, k) == max(length, sum(weights.values()) / k)
