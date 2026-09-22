"""Contract tests for graph.py + critical_path.py (Person A). Skipped until implemented."""

import pytest

from flowforge.schema import Workflow
from flowforge.scheduler import critical_path as cp
from flowforge.scheduler import graph

try:
    graph.build_dag(Workflow.model_validate({"id": "p", "steps": [{"id": "a", "type": "mock"}]}))
except NotImplementedError:
    pytest.skip("graph.py not implemented yet", allow_module_level=True)

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


def test_critical_path():
    result = cp.critical_path(graph.build_dag(DIAMOND), W)
    assert result.path == ["a", "b", "e"] and result.length_ms == 500


def test_bottom_levels():
    bl = cp.bottom_levels(graph.build_dag(DIAMOND), W)
    assert bl == {"a": 500, "b": 400, "c": 200, "d": 100, "e": 100, "f": 50}


def test_lower_bound():
    # total work 700 / k=2 = 350 < critical path 500
    assert cp.lower_bound_ms(graph.build_dag(DIAMOND), W, k=2) == 500
