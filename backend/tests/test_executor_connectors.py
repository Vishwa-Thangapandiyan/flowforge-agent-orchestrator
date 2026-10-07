"""Per-connector routing in the executor (D10): node lookup, buckets, cache namespaces, fallback."""

import asyncio
import hashlib
import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from flowforge.nodes.base import Node, NodeError, TransientNodeError
from flowforge.schema import Workflow
from flowforge.scheduler.cache import cache_key
from flowforge.scheduler.executor import POLICIES, StepState, run_workflow
from flowforge.scheduler.rate_limit import TokenBucket
from flowforge.storage import Storage

from test_graph_properties import random_dags


class FakeNode(Node):
    """Configurable node: `behaviour` is "ok", "transient", "permanent" or "slow"."""

    def __init__(self, type="llm", connector_id=None, rate_limit_key=None, fallback=None,
                 behaviour="ok", default_for_type=False):
        self.type = type
        self.connector_id = connector_id
        self.rate_limit_key = rate_limit_key
        self.fallback = fallback
        self.default_for_type = default_for_type
        self.behaviour = behaviour
        self.calls = 0

    async def run(self, params):
        self.calls += 1
        if self.behaviour == "transient":
            raise TransientNodeError("try later")
        if self.behaviour == "permanent":
            raise NodeError("bad request")
        if self.behaviour == "slow":
            await asyncio.sleep(1)
        return {"text": f"from {self.connector_id}", "usage": {}}


class CountingBucket(TokenBucket):
    def __init__(self):
        super().__init__(rate_per_min=60_000)
        self.acquired = 0

    async def acquire(self):
        self.acquired += 1
        await super().acquire()


def wf(*steps, **extra):
    return Workflow.model_validate({"id": "t", **extra, "steps": list(steps)})


def llm_step(id, connector=None, prompt=None, **extra):
    step = {"id": id, "type": "llm", "params": {"prompt": prompt or id}, **extra}
    if connector:
        step["connector"] = connector
    return step


async def run(workflow, nodes, **kw):
    kw.setdefault("retry_base_s", 0.001)
    return await run_workflow(workflow, nodes, seed=0, **kw)


# --- lookup ----------------------------------------------------------------------------------

async def test_steps_route_to_their_connector():
    default, gem = FakeNode(connector_id="nim", default_for_type=True), FakeNode(connector_id="gemini")
    result = await run(wf(llm_step("a"), llm_step("b", "gemini")), {"llm": default, "gemini": gem})
    assert result.steps["a"].output["text"] == "from nim"
    assert result.steps["b"].output["text"] == "from gemini"


async def test_unknown_connector_rejected_before_running():
    with pytest.raises(ValueError, match="ghost"):
        await run(wf(llm_step("a", "ghost")), {"llm": FakeNode()})


async def test_connector_type_must_match_step_type():
    with pytest.raises(ValueError, match="type"):
        await run(wf(llm_step("a", "fetch")), {"llm": FakeNode(), "fetch": FakeNode(type="mcp", connector_id="fetch")})


# --- rate-limit buckets ----------------------------------------------------------------------

async def test_each_connector_draws_from_its_own_bucket():
    a, b = CountingBucket(), CountingBucket()
    nodes = {"llm": FakeNode(), "fast": FakeNode(connector_id="fast", rate_limit_key="fast"),
             "slow": FakeNode(connector_id="slow", rate_limit_key="slow")}
    steps = [llm_step(f"f{i}", "fast") for i in range(3)] + [llm_step(f"s{i}", "slow") for i in range(2)]
    await run(wf(*steps), nodes, rate_limits={"fast": a, "slow": b})
    assert (a.acquired, b.acquired) == (3, 2)


async def test_default_nim_key_still_used():
    nim = CountingBucket()
    await run(wf(llm_step("a"), llm_step("b")), {"llm": FakeNode(rate_limit_key="nim")}, rate_limits={"nim": nim})
    assert nim.acquired == 2


# --- cache namespaces ------------------------------------------------------------------------

async def test_same_prompt_on_two_connectors_is_two_calls():
    a, b = FakeNode(connector_id="a"), FakeNode(connector_id="b")
    result = await run(wf(llm_step("x", "a", prompt="same"), llm_step("y", "b", prompt="same")),
                       {"llm": FakeNode(), "a": a, "b": b})
    assert (a.calls, b.calls, result.cache_hits) == (1, 1, 0)


async def test_same_prompt_on_one_connector_is_deduped():
    a = FakeNode(connector_id="a")
    result = await run(wf(llm_step("x", "a", prompt="same"), llm_step("y", "a", prompt="same")),
                       {"llm": FakeNode(), "a": a})
    assert (a.calls, result.cache_hits) == (1, 1)


def test_default_namespace_keeps_the_v1_cache_key():
    params = {"prompt": "hi", "temperature": 0}
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    golden = hashlib.sha256(f"llm\x00{canonical}".encode()).hexdigest()
    assert FakeNode().cache_namespace == "llm"
    assert FakeNode(connector_id="nim", default_for_type=True).cache_namespace == "llm"
    assert cache_key(FakeNode().cache_namespace, params) == golden
    assert FakeNode(connector_id="gemini").cache_namespace == "llm:gemini"


async def test_persistent_cache_rows_use_the_namespace(tmp_path):
    db = Storage(tmp_path / "c.db")
    nodes = {"llm": FakeNode(), "gem": FakeNode(connector_id="gem")}
    await run(wf(llm_step("a", prompt="p", cache=True), llm_step("b", "gem", prompt="p", cache=True)), nodes, storage=db)
    assert db.get_cached(cache_key("llm", {"prompt": "p"}))[0]
    assert db.get_cached(cache_key("llm:gem", {"prompt": "p"}))[0]


# --- fallback --------------------------------------------------------------------------------

async def test_fallback_after_transient_exhaustion():
    events = []
    primary = FakeNode(connector_id="primary", fallback="backup", behaviour="transient")
    backup = FakeNode(connector_id="backup")
    result = await run(wf(llm_step("a", "primary", retries=2)), {"llm": FakeNode(), "primary": primary, "backup": backup},
                       on_event=events.append)
    assert result.status == "succeeded"
    assert primary.calls == 3 and backup.calls == 1
    assert result.steps["a"].answered_by == "backup"
    assert {"type": "fallback", "step_id": "a", "from": "primary", "to": "backup"}.items() <= next(
        e for e in events if e["type"] == "fallback").items()


async def test_fallback_after_timeouts():
    primary = FakeNode(connector_id="primary", fallback="backup", behaviour="slow")
    result = await run(wf(llm_step("a", "primary", retries=0, timeout_s=0.05)),
                       {"llm": FakeNode(), "primary": primary, "backup": FakeNode(connector_id="backup")})
    assert result.status == "succeeded" and result.steps["a"].answered_by == "backup"


async def test_no_fallback_on_permanent_error():
    primary = FakeNode(connector_id="primary", fallback="backup", behaviour="permanent")
    backup = FakeNode(connector_id="backup")
    result = await run(wf(llm_step("a", "primary")), {"llm": FakeNode(), "primary": primary, "backup": backup})
    assert result.steps["a"].state == StepState.FAILED and backup.calls == 0


async def test_fallback_is_one_hop_only():
    a = FakeNode(connector_id="a", fallback="b", behaviour="transient")
    b = FakeNode(connector_id="b", fallback="c", behaviour="transient")
    c = FakeNode(connector_id="c")
    result = await run(wf(llm_step("s", "a", retries=0)), {"llm": FakeNode(), "a": a, "b": b, "c": c})
    assert result.steps["s"].state == StepState.FAILED and c.calls == 0


async def test_fallback_uses_its_own_bucket():
    pa, pb = CountingBucket(), CountingBucket()
    nodes = {"llm": FakeNode(),
             "a": FakeNode(connector_id="a", rate_limit_key="a", fallback="b", behaviour="transient"),
             "b": FakeNode(connector_id="b", rate_limit_key="b")}
    await run(wf(llm_step("s", "a", retries=1)), nodes, rate_limits={"a": pa, "b": pb})
    assert (pa.acquired, pb.acquired) == (2, 1)


async def test_missing_fallback_rejected_before_running():
    with pytest.raises(ValueError, match="fallback"):
        await run(wf(llm_step("a", "p")), {"llm": FakeNode(), "p": FakeNode(connector_id="p", fallback="nope")})


async def test_answered_by_without_fallback():
    result = await run(wf(llm_step("a", "gem")), {"llm": FakeNode(), "gem": FakeNode(connector_id="gem")})
    assert result.steps["a"].answered_by == "gem"


# --- scheduling is unchanged by routing ------------------------------------------------------

class GatedNode(Node):
    """Each call waits until the test releases it, so the run order is fully deterministic."""

    def __init__(self, connector_id=None):
        self.type = "mock"
        self.connector_id = connector_id
        self.waiting: dict[str, asyncio.Event] = {}

    async def run(self, params):
        event = self.waiting[params["step"]] = asyncio.Event()
        await event.wait()
        return {"step": params["step"]}


async def start_order(workflow, nodes, gated, policy):
    order = []
    task = asyncio.create_task(run_workflow(
        workflow, nodes, policy=policy, use_cache=False,
        on_event=lambda e: order.append(e["step_id"]) if e.get("state") == "running" else None))
    idle = 0
    while not task.done():
        for _ in range(50):
            await asyncio.sleep(0)
        if gated.waiting:
            gated.waiting.pop(min(gated.waiting)).set()
            idle = 0
        elif (idle := idle + 1) > 200:  # nothing reached the driven node: fail, don't hang
            task.cancel()
            raise AssertionError(f"run stalled; started so far: {order}")
    await task
    return order


@st.composite
def cases(draw):
    edges = draw(random_dags(max_steps=10))
    return edges, {s: draw(st.integers(1, 8)) for s in edges}, draw(st.integers(1, 4)), draw(st.sampled_from(POLICIES))


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cases())
async def test_routing_through_a_connector_never_changes_the_schedule(case):
    edges, estimates, k, policy = case

    def workflow(connector):
        return Workflow.model_validate({"id": "p", "max_concurrency": k, "steps": [
            {"id": s, "type": "mock", "depends_on": d, "estimated_ms": estimates[s], "params": {"step": s},
             **({"connector": connector} if connector else {})} for s, d in edges.items()]})

    by_type = GatedNode()
    by_connector = GatedNode(connector_id="alt")
    expected = await start_order(workflow(None), {"mock": by_type}, by_type, policy)
    actual = await start_order(workflow("alt"), {"mock": GatedNode(), "alt": by_connector}, by_connector, policy)
    assert actual == expected
