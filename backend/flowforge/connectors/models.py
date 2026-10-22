"""Connector models (D10; MCP D12; local D13). Shape follows CLAUDE.md §7.1.

A connector is configuration: who to call, how to connect, which secret (by reference
only) and how it looks. Nodes are built from connectors; the executor never sees these.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from flowforge.connectors.secrets import SECRET_REF_PATTERN, check_ref

CONNECTOR_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
ENV_VAR_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
# Step types name their default node in the executor's node map (D10), so no connector may use them.
RESERVED_IDS = frozenset({"llm", "mcp", "http", "local", "mock"})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- style (stored now, rendered from Phase 2) --------------------------------------------------

class LettersLogo(_Model):
    type: Literal["letters"] = "letters"
    text: str = Field(max_length=2)


class UploadLogo(_Model):
    type: Literal["upload"] = "upload"
    file: str


class NoLogo(_Model):
    type: Literal["none"] = "none"


class Style(_Model):
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    logo: Annotated[LettersLogo | UploadLogo | NoLogo, Field(discriminator="type")] = NoLogo()


# --- connections, one per type ------------------------------------------------------------------

class LLMConnection(_Model):
    provider: Literal["openai_compatible", "anthropic"]
    base_url: str | None = None  # required for openai_compatible
    model: str
    temperature_default: float = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def _base_url_for_openai_compatible(self) -> LLMConnection:
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("openai_compatible connections need base_url")
        return self


class MCPConnection(_Model):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[Annotated[str, Field(pattern=ENV_VAR_PATTERN)], str] = Field(default_factory=dict)
    env_refs: dict[Annotated[str, Field(pattern=ENV_VAR_PATTERN)],
                   Annotated[str, Field(pattern=SECRET_REF_PATTERN)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _refs_are_names(self) -> MCPConnection:
        _check_env_refs(self.env_refs)
        return self


def _check_env_refs(refs: dict[str, str]) -> None:
    for ref in refs.values():
        check_ref(ref)


class HTTPConnection(_Model):
    base_url: str | None = None
    auth_header: str | None = None  # header name only, e.g. "Authorization"
    auth_scheme: Literal["bearer", "basic", "raw"] | None = None


class LocalConnection(_Model):
    command: list[str] = Field(min_length=1)
    cwd: str
    env: dict[Annotated[str, Field(pattern=ENV_VAR_PATTERN)], str] = Field(default_factory=dict)
    env_refs: dict[Annotated[str, Field(pattern=ENV_VAR_PATTERN)],
                   Annotated[str, Field(pattern=SECRET_REF_PATTERN)]] = Field(default_factory=dict)
    max_output_bytes: int = Field(default=1_000_000, gt=0)

    @model_validator(mode="after")
    def _refs_are_names(self) -> LocalConnection:
        _check_env_refs(self.env_refs)
        return self


# --- connectors ---------------------------------------------------------------------------------

class ConnectorBase(_Model):
    id: str = Field(pattern=CONNECTOR_ID_PATTERN)
    name: str
    role: str = ""
    slot: str | None = None
    style: Style = Field(default_factory=Style)
    secret_ref: str | None = Field(default=None, pattern=SECRET_REF_PATTERN)
    mode: Literal["test", "live"] | None = None
    rate_limit_rpm: float | None = Field(default=None, gt=0)
    data_sent: Literal["all", "redacted_only"] = "all"  # behaviour arrives in Phase 4
    fallback: str | None = Field(default=None, pattern=CONNECTOR_ID_PATTERN)
    created_at: str | None = None

    @model_validator(mode="after")
    def _fallback_not_self(self) -> ConnectorBase:
        check_ref(self.secret_ref)
        if self.id in RESERVED_IDS:
            raise ValueError(f"'{self.id}' is reserved for the {self.id} type's default node; pick another id")
        if self.fallback == self.id:
            raise ValueError(f"connector '{self.id}' cannot fall back to itself")
        return self


class LLMConnector(ConnectorBase):
    type: Literal["llm"]
    connection: LLMConnection


class MCPConnector(ConnectorBase):
    type: Literal["mcp"]
    connection: MCPConnection


class HTTPConnector(ConnectorBase):
    type: Literal["http"]
    connection: HTTPConnection = Field(default_factory=HTTPConnection)


class LocalConnector(ConnectorBase):
    type: Literal["local"]
    connection: LocalConnection


Connector = Annotated[LLMConnector | MCPConnector | HTTPConnector | LocalConnector, Field(discriminator="type")]
_ADAPTER: TypeAdapter[Connector] = TypeAdapter(Connector)


def parse_connector(data: Any) -> Connector:
    return _ADAPTER.validate_python(data)
