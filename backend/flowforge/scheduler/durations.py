"""Step-duration estimates: history (EWMA) → estimated_ms → per-type default (D1). Owner: Person A."""

from __future__ import annotations

from flowforge.schema import Step, Workflow

DEFAULT_ESTIMATE_MS: dict[str, float] = {"llm": 3000, "mcp": 1000, "http": 300}
EWMA_ALPHA = 0.3


def default_estimate(step: Step) -> float:
    if step.type == "mock":
        return float(step.params.get("duration_ms", 100))
    return DEFAULT_ESTIMATE_MS[step.type]


def ewma(previous: float | None, observed: float, alpha: float = EWMA_ALPHA) -> float:
    return observed if previous is None else alpha * observed + (1 - alpha) * previous


def estimate_weights(workflow: Workflow, history: dict[str, float] | None = None) -> dict[str, float]:
    """Weight per step id. `history` maps step id → stored EWMA for this workflow (from storage.py)."""
    raise NotImplementedError
