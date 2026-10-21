"""What a check takes and gives back (D24). Names, addresses and commands only: never a key or a response body."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flowforge.scan.models import DependencyKind

Status = Literal["up", "warn", "down", "skipped"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckTarget(_Model):
    """One dependency to check: from the scan (D21), or a block the user added to the map."""

    id: str
    kind: DependencyKind
    name: str
    target: str | None = None          # a URL without its query, or host:port
    command: list[str] | None = None   # mcp and local: the program and its (redacted) arguments
    model: str | None = None
    catalog: str | None = None
    env_names: list[str] = Field(default_factory=list)   # env names its MCP config gives it
    reads_env: list[str] = Field(default_factory=list)   # env names its own script reads (from the scan)


class CheckResult(_Model):
    id: str
    status: Status
    latency_ms: float | None = None
    summary: str                       # one short sentence, shown on the map
    reason: str | None = None          # the error in the dependency's own words, redacted
    fix: str | None = None             # a likely fix, when the code shows one
    detail: dict[str, Any] = Field(default_factory=dict)   # http status, tool count, model listed…
