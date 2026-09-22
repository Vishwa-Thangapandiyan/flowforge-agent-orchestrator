"""Tests for graph.py (Person A)."""

import pytest

from flowforge.schema import Workflow
from flowforge.scheduler import graph

# a → b → e,  a → c → e,  a → d → f   (durations: a100 b300 c100 d50 e100 f50)
DIAMOND = Workflow.model_validate(
    {
        "id": "diamond",
        "steps": [
            {"id": "a", "type": "mock", "params": {"duration_ms": 100}},
            {"id": "b", "type": "mock", "depends_on": ["a"], "params": {"duration_ms": 300}},
            {"id": "c", "type": "mock", "depends_on": ["a"], "params": {"duration_ms": 100}},
            {"id": "d", "type": "mock", "depends_on": ["a"], "params": {"duration_ms": 50}},
            {"id": "e", "type": "mock", "depends_on": ["b", "c"], "params": {"duration_ms": 100}},
            {"id": "f", "type": "mock", "depends_on": ["d"], "params": {"duration_ms": 50}},
        ],
    }
)
W = {s.id: s.params["duration_ms"] for s in DIAMOND.steps}


def test_topological_order_respects_edges():
    dag = graph.build_dag(DIAMOND)
    order = graph.topological_order(dag)
    pos = {s: i for i, s in enumerate(order)}
    assert sorted(order) == sorted(W)
    for s in DIAMOND.steps:
        for p in s.depends_on:
            assert pos[p] < pos[s.id]


def test_cycle_is_reported():
    cyclic = Workflow.model_validate(
        {
            "id": "cyc",
            "steps": [
                {"id": "a", "type": "mock", "depends_on": ["c"]},
                {"id": "b", "type": "mock", "depends_on": ["a"]},
                {"id": "c", "type": "mock", "depends_on": ["b"]},
            ],
        }
    )
    with pytest.raises(graph.CycleError) as exc:
        graph.build_dag(cyclic)
    cycle = exc.value.cycle
    assert cycle[0] == cycle[-1] and set(cycle) == {"a", "b", "c"}


def test_levels():
    assert [sorted(level) for level in graph.levels(graph.build_dag(DIAMOND))] == [["a"], ["b", "c", "d"], ["e", "f"]]


def test_descendants():
    assert graph.descendants(graph.build_dag(DIAMOND), "a") == {"b", "c", "d", "e", "f"}


def mk(edges: dict[str, list[str]]) -> Workflow:
    """Workflow from {step: depends_on}, steps in dict order."""
    return Workflow.model_validate(
        {"id": "t", "steps": [{"id": s, "type": "mock", "depends_on": d} for s, d in edges.items()]}
    )


def test_ties_broken_by_step_order():
    # all independent → order is exactly the declared order
    assert graph.topological_order(graph.build_dag(mk({"z": [], "a": [], "m": []}))) == ["z", "a", "m"]
    # after 'a' finishes, 'b' and 'c' become ready together; 'c' is declared first
    order = graph.topological_order(graph.build_dag(mk({"a": [], "c": ["a"], "b": ["a"]})))
    assert order == ["a", "c", "b"]


def test_duplicate_depends_on_counted_once():
    dag = graph.build_dag(mk({"a": [], "b": ["a", "a"]}))
    assert dag.parents["b"] == ["a"] and dag.children["a"] == ["b"]
    assert graph.topological_order(dag) == ["a", "b"]


def test_cycle_reported_even_with_acyclic_parts():
    # x → a → b → c → a, plus an unrelated branch and a step downstream of the cycle
    wf = mk({"x": [], "a": ["x", "c"], "b": ["a"], "c": ["b"], "tail": ["c"], "free": []})
    with pytest.raises(graph.CycleError) as exc:
        graph.build_dag(wf)
    cycle = exc.value.cycle
    assert set(cycle) == {"a", "b", "c"}
    # consecutive entries must be real edges, in execution direction
    for parent, child in zip(cycle, cycle[1:]):
        assert parent in wf.step(child).depends_on
    assert str(exc.value) == "cycle: b → c → a → b"  # deterministic: search starts at first leftover step


def test_single_step():
    dag = graph.build_dag(mk({"only": []}))
    assert graph.topological_order(dag) == ["only"]
    assert graph.levels(dag) == [["only"]]
    assert graph.descendants(dag, "only") == set()


def test_levels_use_longest_chain():
    # d depends on a (level 0) and c (level 2) → d is level 3, not 1
    assert graph.levels(graph.build_dag(mk({"a": [], "b": ["a"], "c": ["b"], "d": ["a", "c"]}))) == [
        ["a"], ["b"], ["c"], ["d"]
    ]
