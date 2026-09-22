"""Workflow JSON models and static validation (DECISIONS.md D2, D7).

Validation here is everything that can be checked per-step or pairwise.
Cycle detection needs the whole graph and lives in scheduler/graph.py.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flowforge.templating import referenced_steps

StepType = Literal["llm", "mcp", "http", "mock"]

DEFAULT_TIMEOUT_S: dict[str, float] = {"llm": 60, "mcp": 30, "http": 30, "mock": 30}


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")  # catch typos like "depend_on"

    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: StepType
    depends_on: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    estimated_ms: float | None = Field(default=None, gt=0)
    timeout_s: float | None = Field(default=None, gt=0)
    retries: int = Field(default=2, ge=0, le=10)
    cache: bool | None = None  # None = use the per-type default (D3)
    description: str = ""

    @property
    def effective_timeout_s(self) -> float:
        return self.timeout_s if self.timeout_s is not None else DEFAULT_TIMEOUT_S[self.type]


class Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""
    max_concurrency: int = Field(default=4, ge=1)
    type_concurrency: dict[StepType, int] = Field(default_factory=dict)
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> Workflow:
        errors: list[str] = []
        ids = [s.id for s in self.steps]
        known = set(ids)

        seen: set[str] = set()
        for sid in ids:
            if sid in seen:
                errors.append(f"duplicate step id '{sid}'")
            seen.add(sid)

        for step in self.steps:
            deps = set(step.depends_on)
            if step.id in deps:
                errors.append(f"step '{step.id}' depends on itself")
            for dep in deps - known:
                errors.append(f"step '{step.id}' depends on unknown step '{dep}'")
            for ref in referenced_steps(step.params) - deps:
                errors.append(
                    f"step '{step.id}' references '{{{{steps.{ref}...}}}}' "
                    f"but '{ref}' is not in its depends_on"
                )

        if errors:
            raise ValueError("; ".join(errors))
        return self

    def step(self, step_id: str) -> Step:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)
