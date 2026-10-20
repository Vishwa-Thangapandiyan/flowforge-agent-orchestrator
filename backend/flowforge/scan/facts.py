"""What one file shows, before the scanner merges files into dependencies (D21). Internal to `scan/`."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UrlHit:
    """A URL literal, or a constant's name, used where a URL goes. `confirmed`: a recognised call or key."""

    line: int
    url: str | None = None      # scheme://host[:port]/path, query dropped; None while `name` is unresolved
    name: str | None = None     # a module-level constant holding the URL (resolved across files)
    confirmed: bool = False
    call_strings: tuple[str, ...] = ()   # the enclosing call's string arguments: call("fetch", ...) → via


@dataclass
class Ref:
    """A value given either as a literal or as the name of a constant (resolved across files)."""

    literal: str | None = None
    name: str | None = None


@dataclass
class LLMClient:
    line: int
    sdk: str                    # the imported package the client class comes from
    base_url: Ref = field(default_factory=Ref)


@dataclass
class FileFacts:
    path: str
    language: str
    imports: list[tuple[str, int]] = field(default_factory=list)          # (package, line)
    urls: list[UrlHit] = field(default_factory=list)
    clients: list[LLMClient] = field(default_factory=list)
    models: list[tuple[Ref, int]] = field(default_factory=list)           # model= values
    env: list[tuple[str, int]] = field(default_factory=list)              # env var names read, never values
    commands: list[tuple[list[str], int]] = field(default_factory=list)   # [program] or [interpreter, script]
    constants: dict[str, tuple[str, int]] = field(default_factory=dict)   # NAME -> (string value, line)
    strings: set[str] = field(default_factory=set)       # short string literals: does the code name ".mcp.json"?
    call_strings: set[str] = field(default_factory=set)  # string arguments of calls: does it name an MCP server?
