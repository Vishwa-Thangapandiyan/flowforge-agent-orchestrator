"""Concurrent list scheduler (D4, D5, D7). Owner: Person B.

Strategy S5 (the FlowForge scheduler):
  - ready heap keyed by -bottom_level (ties: topological index)
  - a step starts only when: a global slot is free (max_concurrency),
    its type slot is free (type_concurrency), and — if its node has a
    rate_limit_key — a token is acquired from that bucket
  - params resolved with templating.resolve() right before the run
  - node call goes through CallCache, wrapped in asyncio.wait_for(timeout)
  - TransientNodeError / timeout → retry with full-jitter backoff
    (or retry_after_s if given); each retry re-acquires a token
  - permanent failure or retries exhausted → mark failed, mark all
    descendants skipped, keep running independent branches
  - emit an event for every state change (for SSE + benchmark logging)

The benchmark's S1–S4 are the same engine with a different ready-queue
policy / concurrency setting, so keep that pluggable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from flowforge.nodes.base import Node
from flowforge.schema import Workflow

Policy = Literal["sequential", "levels", "greedy", "fifo", "critical_path"]


class StepState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    step_id: str
    state: StepState
    output: Any = None
    error: str | None = None
    attempts: int = 0
    cache_hit: bool = False
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class RunResult:
    workflow_id: str
    policy: Policy
    status: Literal["succeeded", "failed"]
    makespan_ms: float
    steps: dict[str, StepResult] = field(default_factory=dict)
    predicted_critical_path: list[str] = field(default_factory=list)
    actual_critical_path: list[str] = field(default_factory=list)
    api_calls: int = 0
    cache_hits: int = 0


Event = dict[str, Any]


async def run_workflow(
    workflow: Workflow,
    nodes: dict[str, Node],
    *,
    policy: Policy = "critical_path",
    use_cache: bool = True,
    history: dict[str, float] | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> RunResult:
    raise NotImplementedError
