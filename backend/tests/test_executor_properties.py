"""Scheduler invariants on random DAGs, for every policy."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from flowforge.nodes.mock_node import MockNode
from flowforge.schema import Workflow
from flowforge.scheduler.executor import POLICIES, StepState, run_workflow

from test_graph_properties import random_dags


def mock_workflow(edges, durations, k):
    return Workflow.model_validate({
        "id": "p", "max_concurrency": k,
        "steps": [{"id": s, "type": "mock", "depends_on": d, "params": {"duration_ms": durations[s], "step": s}}
                  for s, d in edges.items()],
    })


@st.composite
def cases(draw):
    edges = draw(random_dags(max_steps=12))
    durations = {s: draw(st.integers(1, 8)) for s in edges}
    return edges, durations, draw(st.integers(1, 4)), draw(st.sampled_from(POLICIES))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cases())
async def test_invariants(case):
    edges, durations, k, policy = case
    wf = mock_workflow(edges, durations, k)
    result = await run_workflow(wf, {"mock": MockNode()}, policy=policy, use_cache=False)
    steps = result.steps

    assert result.status == "succeeded"
    assert all(r.state == StepState.SUCCEEDED and r.attempts == 1 for r in steps.values())
    for child, parents in edges.items():
        for p in parents:
            assert steps[p].finished_at <= steps[child].started_at

    limit = 1 if policy == "sequential" else (len(edges) if policy == "greedy" else k)
    for r in steps.values():
        overlapping = sum(1 for o in steps.values() if o.started_at <= r.started_at < o.finished_at)
        assert overlapping <= limit
