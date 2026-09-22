"""Benchmark tooling: the generator's guarantees and a tiny end-to-end run."""

import random
import sys
from pathlib import Path

from flowforge.scheduler import graph

BENCH = Path(__file__).resolve().parents[2] / "benchmarks"
sys.path.insert(0, str(BENCH))

import random_dag  # noqa: E402
import run_benchmark  # noqa: E402


def test_generated_dags_are_valid_and_shuffled():
    rng = random.Random(1)
    shuffled = 0
    for _ in range(50):
        spec = random_dag.generate(rng, n_steps=15, edge_prob=0.3, k=3)
        dag = graph.build_dag(spec.workflow)  # raises on a cycle
        assert len(dag.nodes) == 15 and set(spec.weights_ms) == set(dag.nodes)
        assert all(len(p) <= 4 for p in dag.parents.values())
        order = graph.topological_order(dag)
        shuffled += order != [s.id for s in spec.workflow.steps]
    assert shuffled > 25  # declared order is usually not already topological


def test_duplicates_share_params_and_duration():
    spec = random_dag.generate(random.Random(3), n_steps=40, edge_prob=0.1, dup_prob=0.5)
    by_call = {}
    for s in spec.workflow.steps:
        by_call.setdefault(s.params["call"], set()).add(s.params["duration_ms"])
    assert any(len([s for s in spec.workflow.steps if s.params["call"] == c]) > 1 for c in by_call)
    assert all(len(durations) == 1 for durations in by_call.values())


def test_measured_latencies_are_sampled(tmp_path):
    path = tmp_path / "lat.json"
    path.write_text('{"llm": [1234.0], "http": [], "mcp": [99.0]}')
    model = random_dag.LatencyModel.load(path)
    rng = random.Random(0)
    assert model.sample("llm", rng) == 1234.0
    assert model.sample("http", rng) > 0  # empty list → default distribution


def test_sim_track_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(run_benchmark, "RESULTS", tmp_path)
    monkeypatch.setattr(run_benchmark, "LATENCIES", tmp_path / "none.json")
    run_benchmark.main(["sim", "--graphs", "2", "--min-steps", "4", "--max-steps", "6", "--scale", "0.002"])
    csvs = list(tmp_path.glob("sim_*.csv"))
    assert len(csvs) == 1 and len(csvs[0].read_text().splitlines()) == 1 + 2 * 10  # header + graphs × variants
    summary = next(tmp_path.glob("sim_*.md")).read_text()
    assert "Critical path vs FIFO" in summary and "| critical_path | on |" in summary


def test_mean_ci():
    assert run_benchmark.mean_ci([2.0]) == (2.0, 0.0)
    m, ci = run_benchmark.mean_ci([1.0, 3.0])
    assert m == 2.0 and ci > 0
