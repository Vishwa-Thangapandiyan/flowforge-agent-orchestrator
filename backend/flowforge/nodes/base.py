"""The interface every step type implements, plus the error split the executor retries on (D7)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar


class NodeError(Exception):
    """Permanent failure — do not retry (bad request, auth error, ...)."""


class TransientNodeError(NodeError):
    """Retryable failure: 429, 5xx, timeout, connection error.

    `retry_after_s` carries a server-provided Retry-After hint when there is one.
    """

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class Node(ABC):
    type: ClassVar[str]
    # Name of the rate-limit bucket this node draws from (None = unlimited).
    rate_limit_key: ClassVar[str | None] = None

    @abstractmethod
    async def run(self, params: dict[str, Any]) -> Any:
        """Execute with fully resolved params and return a JSON-serialisable output."""

    def cacheable_across_runs(self, params: dict[str, Any]) -> bool:
        """Per-type default for the persistent cache (D3). Overridden by step.cache."""
        return False
