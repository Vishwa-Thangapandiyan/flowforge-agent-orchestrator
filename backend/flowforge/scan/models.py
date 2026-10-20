"""The scan's output (D21). Names, hosts, paths and `file:line` only: never a key, query string or env value."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DependencyKind = Literal["llm", "api", "mcp", "local"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScanEvidence(_Model):
    """One place in the repo that shows the dependency. `lines` is a redacted excerpt around `ref`."""

    type: Literal["code"] = "code"
    ref: str                       # "services/llm.py:5"
    text: str = ""                 # one short sentence: what this line shows
    first_line: int | None = None  # the excerpt's first line number
    lines: list[str] = Field(default_factory=list, max_length=5)
    highlight: int | None = None   # the line `ref` points at


class Dependency(_Model):
    id: str                        # stable: llm-<provider>, api-<host or service>, mcp-<name>, local-<program>
    kind: DependencyKind
    name: str
    catalog: str | None = None     # a known service's id (presets.SERVICES), for its tile
    target: str | None = None      # what a check would reach: a URL without its query, host:port, or a command
    targets: list[str] = Field(default_factory=list)  # every distinct URL seen, for a service on several hosts
    model: str | None = None       # llm only
    command: list[str] | None = None  # mcp and local: the program and its arguments (redacted)
    status: Literal["confirmed", "unconfirmed"] = "confirmed"
    scope: Literal["app", "dev_tool"] = "app"   # dev_tool: an MCP server only your coding tools use
    via: str | None = None         # reached through this MCP server, e.g. "mcp-fetch"
    evidence: list[ScanEvidence] = Field(default_factory=list)   # at most 10
    places: int = 0                # how many places show it in all
    env_names: list[str] = Field(default_factory=list)


class EnvName(_Model):
    name: str
    ref: str


class ScanResult(_Model):
    root: str                      # the folder's name, not its full path
    files_scanned: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)
    languages: dict[str, int] = Field(default_factory=dict)
    dependencies: list[Dependency] = Field(default_factory=list)
    env_names: list[EnvName] = Field(default_factory=list)
    findings: list[dict[str, str]] = Field(default_factory=list)   # security findings arrive in Phase 6
