import pytest

from flowforge.schema import Workflow
from flowforge.scheduler.executor import StepState, run_workflow
from flowforge.scheduler.rate_limit import TokenBucket
from flowforge.nodes.mock_node import MockNode
from flowforge.storage import Storage


def mk(steps, **wf):
    return Workflow.model_validate({"id": "t", **wf, "steps": steps})


def m(id, ms, deps=(), **params):
    """Mock step. Params include the step id so distinct steps never look like duplicate calls."""
    return {"id": id, "type": "mock", "depends_on": list(deps), "params": {"duration_ms": ms, "step": id, **params}}


def dup(id, ms, deps=()):
    """Mock step whose params are identical to every other dup() with the same duration."""
    return {"id": id, "type": "mock", "depends_on": list(deps), "params": {"duration_ms": ms}}


async def run(wf, **kw):
    node = kw.pop("node", None) or MockNode()
    kw.setdefault("retry_base_s", 0.001)
    return await run_workflow(wf, {"mock": node}, seed=0, **kw), node


DIAMOND = mk(
    [m("a", 20), m("b", 60, ["a"]), m("c", 20, ["a"]), m("d", 10, ["a"]), m("e", 20, ["b", "c"]), m("f", 10, ["d"])],
    max_concurrency=2,
)


async def test_diamond_meets_lower_bound():
    result, _ = await run(DIAMOND)
    assert result.status == "succeeded"
    assert result.predicted_critical_path == ["a", "b", "e"]
    assert result.actual_critical_path == ["a", "b", "e"]
    assert 100 <= result.makespan_ms < 140  # lower bound is 100


async def test_dependencies_respected():
    result, _ = await run(DIAMOND)
    s = result.steps
    for step in DIAMOND.steps:
        for p in step.depends_on:
            assert s[p].finished_at <= s[step.id].started_at


# three short independent steps declared first, then a 3-step chain
TRAP = mk([m("x1", 40), m("x2", 40), m("x3", 40), m("l1", 40), m("l2", 40, ["l1"]), m("l3", 40, ["l2"])],
          max_concurrency=2)


async def test_critical_path_beats_fifo():
    cp, _ = await run(TRAP, policy="critical_path")
    fifo, _ = await run(TRAP, policy="fifo")
    # cp starts the chain at t=0 → 3 rounds (120 ms); fifo starts it late → 4 rounds (160 ms)
    assert cp.makespan_ms < 150 <= fifo.makespan_ms


async def test_sequential_is_sum_of_work():
    result, _ = await run(TRAP, policy="sequential")
    assert result.makespan_ms >= 240


async def test_levels_barrier_vs_greedy():
    wf = mk([m("a", 20), m("b", 20, ["a"]), m("c", 60)], max_concurrency=4)
    levels, _ = await run(wf, policy="levels")
    greedy, _ = await run(wf, policy="greedy")
    assert greedy.makespan_ms < 75 and levels.makespan_ms >= 80  # b waits for c's layer


async def test_failure_skips_descendants_only():
    wf = mk([m("a", 5), m("b", 5, ["a"], fail="permanent"), m("c", 5, ["a"]), m("e", 5, ["b", "c"]), m("f", 5, ["c"])])
    result, _ = await run(wf)
    states = {s: r.state for s, r in result.steps.items()}
    assert states == {"a": StepState.SUCCEEDED, "b": StepState.FAILED, "c": StepState.SUCCEEDED,
                      "e": StepState.SKIPPED, "f": StepState.SUCCEEDED}
    assert result.status == "failed"


async def test_transient_error_is_retried():
    wf = mk([{**m("a", 1, fail="transient", fail_times=2), "retries": 2}])
    result, _ = await run(wf)
    assert result.status == "succeeded" and result.steps["a"].attempts == 3 and result.api_calls == 3


async def test_retries_exhausted():
    wf = mk([{**m("a", 1, fail="transient"), "retries": 1}])
    result, _ = await run(wf)
    assert result.steps["a"].state == StepState.FAILED and result.steps["a"].attempts == 2


async def test_permanent_error_not_retried():
    result, _ = await run(mk([m("a", 1, fail="permanent")]))
    assert result.steps["a"].attempts == 1


async def test_timeout():
    wf = mk([{**m("slow", 500), "timeout_s": 0.02, "retries": 0}, m("other", 5)])
    result, _ = await run(wf)
    assert result.steps["slow"].error == "TimeoutError"
    assert result.steps["other"].state == StepState.SUCCEEDED
    assert result.makespan_ms < 200


async def test_outputs_flow_through_templates():
    wf = mk([
        m("a", 1, output={"v": 7, "name": "x"}),
        {"id": "b", "type": "mock", "depends_on": ["a"],
         "params": {"duration_ms": 1, "output": {"n": "{{steps.a.output.v}}", "s": "hi {{steps.a.output.name}}"}}},
    ])
    result, _ = await run(wf)
    assert result.steps["b"].output == {"n": 7, "s": "hi x"}


async def test_bad_template_path_fails_step():
    wf = mk([m("a", 1, output={"v": 1}),
             {"id": "b", "type": "mock", "depends_on": ["a"], "params": {"x": "{{steps.a.output.nope}}"}}])
    result, _ = await run(wf)
    assert result.steps["b"].state == StepState.FAILED and "template error" in result.steps["b"].error


async def test_duplicate_calls_made_once():
    wf = mk([dup("a", 30), dup("b", 30), m("c", 30, ["a", "b"])])  # a and b are identical calls
    result, node = await run(wf)
    assert node.calls == 2 and result.cache_hits == 1 and result.api_calls == 2
    uncached, node = await run(wf, use_cache=False)
    assert node.calls == 3 and uncached.cache_hits == 0


async def test_cache_false_opts_out():
    wf = mk([dup("a", 5), {**dup("b", 5), "cache": False}])
    _, node = await run(wf)
    assert node.calls == 2


async def test_persistent_cache_and_duration_history(tmp_path):
    db = Storage(tmp_path / "r.db")
    wf = mk([{**m("a", 20), "cache": True}, m("b", 20, ["a"])])
    first, _ = await run(wf, storage=db)
    assert first.cache_hits == 0 and set(db.duration_history("t")) == {"a", "b"}
    second, node = await run(wf, storage=db)
    assert node.calls == 1 and second.steps["a"].cache_hit  # a from disk, b re-run (mock default: no persist)


class LimitedMock(MockNode):
    rate_limit_key = "nim"


async def test_rate_limit_applies_across_parallel_steps():
    wf = mk([m(f"s{i}", 1) for i in range(4)], max_concurrency=4)
    result, _ = await run(wf, node=LimitedMock(), rate_limits={"nim": TokenBucket(600, capacity=1)})
    assert result.makespan_ms >= 280  # 1 free token, then 3 more at 100 ms each


async def test_type_concurrency_limit():
    wf = mk([m(f"s{i}", 30) for i in range(4)], max_concurrency=4, type_concurrency={"mock": 1})
    result, _ = await run(wf)
    assert result.makespan_ms >= 120


async def test_events_stream():
    events = []
    await run(mk([m("a", 1), m("b", 1, ["a"])]), on_event=events.append)
    assert events[0]["type"] == "run" and events[0]["state"] == "started"
    assert [(e["step_id"], e["state"]) for e in events if e["type"] == "step"] == [
        ("a", "ready"), ("a", "running"), ("a", "succeeded"),
        ("b", "ready"), ("b", "running"), ("b", "succeeded"),
    ]
    assert events[-1]["state"] == "succeeded"


async def test_missing_node_type_rejected():
    with pytest.raises(ValueError, match="no node registered"):
        await run_workflow(mk([{"id": "a", "type": "llm"}]), {"mock": MockNode()})
