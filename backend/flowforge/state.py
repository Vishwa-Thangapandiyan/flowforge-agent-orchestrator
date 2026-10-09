"""App state shared by the API routers: nodes, buckets, storage, redaction, live runs (D16)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException

from flowforge.connectors.registry import Registry
from flowforge.nodes.base import Node
from flowforge.scheduler.executor import Event
from flowforge.scheduler.rate_limit import TokenBucket
from flowforge.schema import Workflow
from flowforge.security.logfilter import Redactor
from flowforge.storage import Storage


def plain(value: Any, redactor: Redactor) -> Any:
    """Redacted, JSON-shaped copy, identical to what a later read from storage returns."""
    return json.loads(json.dumps(redactor.redact(value), default=str))


@dataclass
class Run:
    """A run while this server process is executing it. History lives in storage."""

    id: str
    workflow: Workflow
    storage: Storage
    redactor: Redactor
    events: list[Event] = field(default_factory=list)
    status: str = "running"
    result: dict[str, Any] | None = None
    error: str | None = None
    done: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[Any] | None = None

    def push(self, event: Event) -> None:
        """Every event is redacted before it is kept, stored or streamed (D16)."""
        event = plain(event, self.redactor)
        self.events.append(event)
        self.storage.append_event(self.id, len(self.events) - 1, event)
        self.changed.set()


@dataclass
class AppState:
    nodes: dict[str, Node]
    rate_limits: dict[str, TokenBucket]
    storage: Storage
    registry: Registry
    redactor: Redactor
    file_managed: set[str] = field(default_factory=set)  # ids from connectors.json: read-only (D16)
    connector_tests: dict[str, dict[str, Any]] = field(default_factory=dict)  # last "Test connection"
    retired_nodes: list[Node] = field(default_factory=list)  # replaced nodes, closed at shutdown
    runs: dict[str, Run] = field(default_factory=dict)
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    shutting_down: bool = False
    example: bool = False  # example-data mode (D16): the UI labels everything as example data
    flows: Any = None  # flowmap.service.FlowService (D17); Any avoids an import cycle


current: AppState | None = None


def app_state() -> AppState:
    if current is None:
        raise HTTPException(503, "app not started")
    return current
