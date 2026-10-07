"""Connector models and secret refs (D10, D12, D13)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flowforge.connectors.models import (
    HTTPConnector,
    LLMConnector,
    LocalConnector,
    MCPConnector,
    parse_connector,
)
from flowforge.connectors.secrets import SecretRefError, resolve_secret
from flowforge.scheduler.durations import default_estimate
from flowforge.schema import DEFAULT_TIMEOUT_S, Workflow

FAKE_KEY = "nvapi-FAKEFAKEFAKE1234"
WORKFLOWS = Path(__file__).parent.parent / "workflows"


def llm(**over):
    return {"id": "gemini", "type": "llm", "name": "Gemini",
            "connection": {"provider": "openai_compatible", "base_url": "https://example.test/v1", "model": "m"},
            "secret_ref": "env:GEMINI_API_KEY", **over}


# --- models ---------------------------------------------------------------------------------

def test_connection_shape_follows_type():
    assert isinstance(parse_connector(llm()), LLMConnector)
    assert isinstance(parse_connector({"id": "fetch", "type": "mcp", "name": "Fetch",
                                       "connection": {"command": "uvx", "args": ["mcp-server-fetch"]}}), MCPConnector)
    assert isinstance(parse_connector({"id": "api", "type": "http", "name": "API",
                                       "connection": {"base_url": "https://api.test"}}), HTTPConnector)
    assert isinstance(parse_connector({"id": "sh", "type": "local", "name": "Script",
                                       "connection": {"command": ["python"], "cwd": "."}}), LocalConnector)


def test_connection_fields_must_match_type():
    with pytest.raises(ValidationError):  # an llm connection on an mcp connector
        parse_connector({**llm(), "type": "mcp"})


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        parse_connector(llm(api_key=FAKE_KEY))  # a raw key field must not exist anywhere
    with pytest.raises(ValidationError):
        parse_connector(llm(connection={"provider": "anthropic", "model": "m", "api_key": FAKE_KEY}))


def test_connector_id_pattern():
    parse_connector(llm(id="image-studio"))
    for bad in ["", "9lives", "has space", "a/b", "x" * 65]:
        with pytest.raises(ValidationError):
            parse_connector(llm(id=bad))


def test_secret_ref_format():
    parse_connector(llm(secret_ref="vault:GEMINI_API_KEY"))
    parse_connector(llm(secret_ref=None))
    for bad in [FAKE_KEY, "env:", "file:/etc/passwd", "env:lower"]:
        with pytest.raises(ValidationError):
            parse_connector(llm(secret_ref=bad))


@pytest.mark.parametrize("name", ["SK_TEST_FAKEFAKE12345678", "RZP_LIVE_FAKE1234567", "SK_LIVE_FAKEFAKE12345678", "AIZAFAKEFAKEFAKEFAKE12"])
def test_a_key_pasted_as_a_variable_name_is_refused(name):
    """A key upper-cased into the name field must not be stored as env:<the key> (D16)."""
    with pytest.raises(ValidationError, match="looks like a key"):
        parse_connector(llm(secret_ref=f"env:{name}"))
    with pytest.raises(ValidationError, match="looks like a key"):
        parse_connector({"id": "m", "type": "mcp", "name": "M",
                         "connection": {"command": "x", "env_refs": {"TOKEN": f"env:{name}"}}})


def test_fallback_cannot_point_at_itself():
    with pytest.raises(ValidationError, match="itself"):
        parse_connector(llm(fallback="gemini"))


def test_round_trip_json():
    c = parse_connector(llm(rate_limit_rpm=15, style={"color": "#E4572E", "logo": {"type": "letters", "text": "Ge"}}))
    assert parse_connector(json.loads(c.model_dump_json())) == c


# --- secret refs -----------------------------------------------------------------------------

def test_env_ref_resolves(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert resolve_secret("env:GEMINI_API_KEY") == FAKE_KEY


def test_missing_env_ref_names_the_variable_not_a_value(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SecretRefError, match="GEMINI_API_KEY is not set"):
        resolve_secret("env:GEMINI_API_KEY")


def test_vault_ref_is_reserved_for_phase_3():
    with pytest.raises(SecretRefError, match="Phase 3"):
        resolve_secret("vault:GEMINI_API_KEY")


def test_no_ref_means_no_secret():
    assert resolve_secret(None) is None


# --- Step.connector and the local type -------------------------------------------------------

@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.json")), ids=lambda p: p.name)
def test_existing_workflows_still_valid_without_connector(path):
    wf = Workflow.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert all(s.connector is None for s in wf.steps)


def test_step_accepts_connector():
    wf = Workflow.model_validate({"id": "t", "steps": [
        {"id": "a", "type": "llm", "connector": "gemini", "params": {"prompt": "hi"}}]})
    assert wf.steps[0].connector == "gemini"


def test_step_connector_pattern():
    with pytest.raises(ValidationError):
        Workflow.model_validate({"id": "t", "steps": [{"id": "a", "type": "llm", "connector": "no spaces"}]})


def test_local_type_defaults():
    wf = Workflow.model_validate({"id": "t", "steps": [{"id": "a", "type": "local", "connector": "sh"}]})
    assert wf.steps[0].effective_timeout_s == DEFAULT_TIMEOUT_S["local"] == 60
    assert default_estimate(wf.steps[0]) == 1000


def test_type_concurrency_accepts_local():
    Workflow.model_validate({"id": "t", "type_concurrency": {"local": 1},
                             "steps": [{"id": "a", "type": "local", "connector": "sh"}]})
