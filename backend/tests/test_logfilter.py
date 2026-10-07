"""Minimal redaction pulled forward into Phase 2 (D16): key shapes + configured key values."""

import base64
import logging

import pytest
from hypothesis import given
from hypothesis import strategies as st

from flowforge.connectors.models import parse_connector
from flowforge.security.logfilter import (
    REDACTED,
    Redactor,
    install_log_redaction,
    secret_values_for,
)

FAKE_KEYS = [
    "sk_test_FAKEFAKE12345678",
    "sk_live_FAKEFAKE12345678",
    "rk_test_FAKEFAKE12345678",
    "rzp_test_FAKE1234567",
    "rzp_live_FAKE1234567",
    "AIzaFAKEFAKEFAKEFAKEFAKE1234",
    "nvapi-FAKEFAKEFAKE1234",
    "sk-ant-FAKEFAKEFAKE1234",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.FAKEsignatureFAKE",
]
PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvFAKEFAKEFAKE\nFAKEFAKE==\n-----END PRIVATE KEY-----"


@pytest.mark.parametrize("key", FAKE_KEYS)
def test_known_key_shapes_are_masked(key):
    out = Redactor().redact_text(f"calling with {key} now")
    assert key not in out and REDACTED in out and out.startswith("calling with ")


def test_pem_block_is_masked():
    assert "MIIEv" not in Redactor().redact_text(f"cert:\n{PEM}\nend")


def test_configured_values_and_their_basic_auth_form_are_masked():
    value = "my-custom-token-123"  # matches no known shape; known only because a connector names it
    r = Redactor([value])
    assert value not in r.redact_text(f"token={value}")
    encoded = base64.b64encode(value.encode()).decode()
    assert encoded not in r.redact_text(f"Authorization: Basic {encoded}")


def test_short_values_are_never_masked():
    r = Redactor(["abc", "1234567"])
    assert r.redact_text("abc 1234567 abcdef") == "abc 1234567 abcdef"


def test_ordinary_text_is_left_alone():
    text = "Fetched 3 payments; sk is a prefix; key_id=order_42; risk: low"
    assert Redactor().redact_text(text) == text


def test_nested_structures():
    r = Redactor(["configured-secret-value"])
    data = {"a": ["x", {"b": "token sk_test_FAKEFAKE12345678"}], "c": ("configured-secret-value", 3), "n": None}
    out = r.redact(data)
    assert out == {"a": ["x", {"b": f"token {REDACTED}"}], "c": [REDACTED, 3], "n": None}


def test_secret_values_come_from_connector_refs_and_nim(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-fake-value-123")
    monkeypatch.setenv("TOOL_TOKEN", "tool-fake-value-456")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-fake-value-789")
    monkeypatch.setenv("UNRELATED", "not-a-secret-value")
    connectors = [
        parse_connector({"id": "gemini", "type": "llm", "name": "G", "secret_ref": "env:GEMINI_API_KEY",
                         "connection": {"provider": "openai_compatible", "base_url": "https://x.test", "model": "m"}}),
        parse_connector({"id": "tool", "type": "mcp", "name": "T",
                         "connection": {"command": "x", "env_refs": {"TOKEN": "env:TOOL_TOKEN"}}}),
        parse_connector({"id": "vaulted", "type": "llm", "name": "V", "secret_ref": "vault:LATER",
                         "connection": {"provider": "anthropic", "model": "m"}}),
    ]
    assert secret_values_for(connectors) == {"gemini-fake-value-123", "tool-fake-value-456", "nvidia-fake-value-789"}


def test_log_records_are_redacted(caplog):
    r = Redactor(["configured-secret-value"])
    restore = install_log_redaction(r)
    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("uvicorn.error").info("key %s and %s", "sk_test_FAKEFAKE12345678", "configured-secret-value")
            logging.getLogger("flowforge.anything").warning("plain configured-secret-value")
    finally:
        restore()
    text = caplog.text
    assert "sk_test_FAKEFAKE12345678" not in text and "configured-secret-value" not in text
    assert text.count(REDACTED) == 3


def test_structured_log_records_still_format():
    """uvicorn's access formatter unpacks record.args, so args must stay a tuple (just redacted)."""
    from uvicorn.logging import AccessFormatter

    r = Redactor(["configured-secret-value"])
    restore = install_log_redaction(r)
    try:
        record = logging.getLogger("uvicorn.access").makeRecord(
            "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:5000", "GET", "/runs?token=configured-secret-value", "1.1", 200), None)
    finally:
        restore()
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)
    assert line == '127.0.0.1:5000 - "GET /runs?token=[REDACTED] HTTP/1.1" 200 OK'


def test_tracebacks_are_redacted():
    r = Redactor(["configured-secret-value"])
    restore = install_log_redaction(r)
    try:
        try:
            raise ValueError("bad key configured-secret-value")
        except ValueError:
            import sys
            record = logging.getLogger("x").makeRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    finally:
        restore()
    text = logging.Formatter().format(record)
    assert "configured-secret-value" not in text and "ValueError: bad key [REDACTED]" in text


@given(
    st.lists(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=20), min_size=1, max_size=6),
    st.lists(st.sampled_from(FAKE_KEYS), min_size=1, max_size=4),
)
def test_embedded_keys_never_survive_and_redaction_is_idempotent(chunks, keys):
    text = " ".join(c + " " + k for c, k in zip(chunks, keys, strict=False))
    r = Redactor()
    once = r.redact_text(text)
    assert not any(k in once for k in keys)
    assert r.redact_text(once) == once
