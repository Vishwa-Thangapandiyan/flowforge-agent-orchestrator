"""Concurrent list scheduler (D4, D5, D7). Owner: Person B.

One dispatcher loop owns all scheduling decisions; each running step is an asyncio task.

  - ready steps sit in a heap whose key depends on the policy (see _priority)
  - a step starts only when a global slot and its type slot are free
    (a step whose identical call is already cached/in flight starts without a slot —
    it only waits, it doesn't work)
  - inside the task: rate-limit token → node.run under asyncio.wait_for(timeout);
    transient errors retry with full-jitter backoff (or the server's Retry-After),
    and every attempt takes a fresh token
  - on failure every descendant is marked skipped; independent branches keep going

Policies (benchmark strategies S1–S5 from D6):
  sequential     k = 1, topological order
  levels         BFS layers with a barrier: nothing from layer i+1 starts until layer i is done
  greedy         unlimited concurrency, no type limits
  fifo           k slots, first-ready first-served
  critical_path  k slots, highest bottom level first (HLFET) — FlowForge's scheduler
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from flowforge import templating
from flowforge.nodes.base import Node, NodeError, TransientNodeError
from flowforge.schema import Step, Workflow
from flowforge.scheduler import graph
from flowforge.scheduler.cache import CallCache, cache_key
from flowforge.scheduler.critical_path import bottom_levels, critical_path
from flowforge.scheduler.durations import estimate_weights
from flowforge.scheduler.rate_limit import TokenBucket

Policy = Literal["sequential", "levels", "greedy", "fifo", "critical_path"]
POLICIES: tuple[Policy, ...] = ("sequential", "levels", "greedy", "fifo", "critical_path")


class StepState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


TERMINAL = {StepState.SUCCEEDED, StepState.FAILED, StepState.SKIPPED}


@dataclass
class StepResult:
    step_id: str
    state: StepState = StepState.PENDING
    output: Any = None
    error: str | None = None
    attempts: int = 0
    cache_hit: bool = False
    started_at: float | None = None   # seconds since run start
    finished_at: float | None = None
    call_ms: float | None = None      # the successful node call alone: no token wait, no backoff

    @property
    def duration_ms(self) -> float:
        if self.started_at is None or self.finished_at is None:
            return 0.0
        return (self.finished_at - self.started_at) * 1000


@dataclass
class RunResult:
    workflow_id: str
    policy: Policy
    status: Literal["succeeded", "failed"]
    makespan_ms: float
    steps: dict[str, StepResult] = field(default_factory=dict)
    predicted_critical_path: list[str] = field(default_factory=list)
    predicted_critical_path_ms: float = 0.0
    actual_critical_path: list[str] = field(default_factory=list)
    actual_critical_path_ms: float = 0.0
    api_calls: int = 0
    cache_hits: int = 0


Event = dict[str, Any]


def backoff_s(attempt: int, error: Exception, rng: random.Random, base_s: float, cap_s: float) -> float:
    """Full jitter: uniform(0, min(cap, base·2^attempt)); a server Retry-After wins."""
    if isinstance(error, TransientNodeError) and error.retry_after_s is not None:
        return error.retry_after_s
    return rng.uniform(0, min(cap_s, base_s * 2**attempt))


async def run_workflow(
    workflow: Workflow,
    nodes: dict[str, Node],
    *,
    policy: Policy = "critical_path",
    use_cache: bool = True,
    max_concurrency: int | None = None,
    rate_limits: dict[str, TokenBucket] | None = None,
    storage: Any | None = None,
    history: dict[str, float] | None = None,
    on_event: Callable[[Event], None] | None = None,
    retry_base_s: float = 1.0,
    retry_cap_s: float = 30.0,
    seed: int | None = None,
) -> RunResult:
    """Execute `workflow`. `nodes` maps step type → Node; `rate_limits` maps a node's
    rate_limit_key → shared TokenBucket. `storage` (optional) enables the persistent
    cache, supplies duration history and records this run's measured durations.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    missing = {s.type for s in workflow.steps} - nodes.keys()
    if missing:
        raise ValueError(f"no node registered for step type(s): {sorted(missing)}")

    dag = graph.build_dag(workflow)
    topo = graph.topological_order(dag)
    topo_index = {s: i for i, s in enumerate(topo)}
    level = {s: i for i, layer in enumerate(graph.levels(dag)) for s in layer}

    if history is None:
        history = storage.duration_history(workflow.id) if storage is not None else {}
    weights = estimate_weights(workflow, history)
    bl = bottom_levels(dag, weights)
    predicted = critical_path(dag, weights)

    k = max_concurrency or workflow.max_concurrency
    type_limits: dict[str, int] = dict(workflow.type_concurrency)
    if policy == "sequential":
        k = 1
    elif policy == "greedy":
        k, type_limits = math.inf, {}

    steps = {s.id: s for s in workflow.steps}
    results = {s.id: StepResult(s.id) for s in workflow.steps}
    outputs: dict[str, Any] = {}
    unmet = {s: len(dag.parents[s]) for s in dag.nodes}
    cache = CallCache(storage)
    rate_limits = rate_limits or {}
    rng = random.Random(seed)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    ready_seq = itertools.count()

    def now() -> float:
        return loop.time() - t0

    def emit(event: Event) -> None:
        if on_event is not None:
            on_event({"t": round(now(), 4), **event})

    def set_state(step_id: str, state: StepState, **extra: Any) -> None:
        results[step_id].state = state
        emit({"type": "step", "step_id": step_id, "state": state.value, **extra})

    def _priority(step_id: str) -> tuple:
        if policy == "critical_path":
            return (-bl[step_id], topo_index[step_id])
        if policy == "fifo":
            return (next(ready_seq),)
        if policy == "levels":
            return (level[step_id], topo_index[step_id])
        return (topo_index[step_id],)

    ready: list[tuple[tuple, str]] = []

    def make_ready(step_id: str) -> None:
        set_state(step_id, StepState.READY)
        heapq.heappush(ready, (_priority(step_id), step_id))

    # --- one step's execution (runs as its own task) ---------------------------

    def caching_for(step: Step, params: dict[str, Any]) -> tuple[bool, bool]:
        """(dedupe within run, persist across runs) per D3."""
        if not use_cache or step.cache is False:
            return False, False
        persistent = step.cache is True or nodes[step.type].cacheable_across_runs(params)
        return True, persistent and storage is not None

    async def call_with_retries(step: Step, params: dict[str, Any]) -> Any:
        node = nodes[step.type]
        bucket = rate_limits.get(node.rate_limit_key) if node.rate_limit_key else None
        for attempt in range(step.retries + 1):
            if bucket is not None:
                await bucket.acquire()
            results[step.id].attempts += 1
            call_start = loop.time()
            try:
                output = await asyncio.wait_for(node.run(params), step.effective_timeout_s)
                results[step.id].call_ms = (loop.time() - call_start) * 1000
                return output
            except (TransientNodeError, TimeoutError) as exc:
                if attempt == step.retries:
                    raise
                delay = backoff_s(attempt, exc, rng, retry_base_s, retry_cap_s)
                emit({"type": "retry", "step_id": step.id, "attempt": attempt + 1,
                      "error": str(exc) or type(exc).__name__, "delay_s": round(delay, 3)})
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def execute(step: Step, params: dict[str, Any]) -> Any:
        dedupe, persistent = caching_for(step, params)
        if not dedupe:
            return await call_with_retries(step, params)
        value, hit = await cache.get_or_run(
            cache_key(step.type, params), lambda: call_with_retries(step, params), persistent
        )
        results[step.id].cache_hit = hit
        return value

    # --- dispatcher --------------------------------------------------------------

    running: dict[asyncio.Task[Any], tuple[str, bool]] = {}  # task → (step id, holds a slot)
    type_running: dict[str, int] = {}
    slots_used = 0

    def current_level() -> int:
        return min((level[s] for s, r in results.items() if r.state not in TERMINAL), default=0)

    def start(step_id: str, params: dict[str, Any], holds_slot: bool) -> None:
        nonlocal slots_used
        step = steps[step_id]
        if holds_slot:
            slots_used += 1
            type_running[step.type] = type_running.get(step.type, 0) + 1
        results[step_id].started_at = now()
        set_state(step_id, StepState.RUNNING)
        running[asyncio.create_task(execute(step, params))] = (step_id, holds_slot)

    def dispatch() -> None:
        """Start every ready step that can start now, best priority first."""
        blocked: list[tuple[tuple, str]] = []
        gate = current_level() if policy == "levels" else None
        while ready:
            item = heapq.heappop(ready)
            step_id = item[1]
            step = steps[step_id]
            if gate is not None and level[step_id] > gate:
                blocked.append(item)
                continue
            try:
                params = templating.resolve(step.params, outputs)
            except templating.TemplateError as exc:
                fail(step_id, f"template error: {exc}")
                continue
            dedupe, _ = caching_for(step, params)
            if dedupe and cache.has(cache_key(step.type, params)):
                start(step_id, params, holds_slot=False)
                continue
            type_full = type_running.get(step.type, 0) >= type_limits.get(step.type, math.inf)
            if slots_used >= k or type_full:
                blocked.append(item)
                continue
            start(step_id, params, holds_slot=True)
        for item in blocked:
            heapq.heappush(ready, item)

    def fail(step_id: str, error: str) -> None:
        results[step_id].error = error
        results[step_id].finished_at = results[step_id].finished_at or now()
        set_state(step_id, StepState.FAILED, error=error)
        for d in sorted(graph.descendants(dag, step_id), key=topo_index.__getitem__):
            if results[d].state not in TERMINAL:
                set_state(d, StepState.SKIPPED, reason=f"upstream '{step_id}' failed")

    def succeed(step_id: str, output: Any) -> None:
        outputs[step_id] = output
        results[step_id].output = output
        set_state(step_id, StepState.SUCCEEDED, cache_hit=results[step_id].cache_hit,
                  duration_ms=round(results[step_id].duration_ms, 1))
        for child in dag.children[step_id]:
            unmet[child] -= 1
            if unmet[child] == 0 and results[child].state == StepState.PENDING:
                make_ready(child)

    emit({"type": "run", "state": "started", "workflow_id": workflow.id, "policy": policy,
          "predicted_critical_path": predicted.path})
    for s in topo:
        if unmet[s] == 0:
            make_ready(s)

    try:
        dispatch()
        while running:
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                step_id, held = running.pop(task)
                if held:
                    slots_used -= 1
                    type_running[steps[step_id].type] -= 1
                results[step_id].finished_at = now()
                exc = task.exception()
                if exc is None:
                    succeed(step_id, task.result())
                elif isinstance(exc, (NodeError, TimeoutError)):
                    fail(step_id, str(exc) or type(exc).__name__)
                else:  # a bug in a node — still contained to this step
                    fail(step_id, f"{type(exc).__name__}: {exc}")
            dispatch()
    finally:
        for task in running:
            task.cancel()

    # --- results -------------------------------------------------------------------

    stuck = [s for s, r in results.items() if r.state not in TERMINAL]
    assert not stuck, f"scheduler bug: steps never finished: {stuck}"

    measured = {s: r.duration_ms for s, r in results.items()}
    actual = critical_path(dag, measured)
    status: Literal["succeeded", "failed"] = (
        "succeeded" if all(r.state == StepState.SUCCEEDED for r in results.values()) else "failed"
    )
    result = RunResult(
        workflow_id=workflow.id,
        policy=policy,
        status=status,
        makespan_ms=now() * 1000,
        steps=results,
        predicted_critical_path=predicted.path,
        predicted_critical_path_ms=predicted.length_ms,
        actual_critical_path=actual.path,
        actual_critical_path_ms=actual.length_ms,
        api_calls=sum(r.attempts for r in results.values()),
        cache_hits=cache.hits,
    )
    if storage is not None:
        storage.record_durations(
            workflow.id,
            {s: r.duration_ms for s, r in results.items()
             if r.state == StepState.SUCCEEDED and not r.cache_hit},
        )
    emit({"type": "run", "state": status, "makespan_ms": round(result.makespan_ms, 1),
          "actual_critical_path": actual.path})
    return result
