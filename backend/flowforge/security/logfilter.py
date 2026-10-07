"""Minimal redaction, pulled forward into Phase 2 (D16; full spec in CLAUDE.md §6.4–6.5).

Masks two things as "[REDACTED]":
  - strings shaped like known keys (Stripe, Razorpay, Google, NVIDIA, Anthropic, JWTs, PEM blocks)
  - the current values of env vars that connectors reference (secret_ref / env_refs), plus
    NVIDIA_API_KEY, and their Basic-auth base64 form. Values under 8 characters are skipped.

It is applied to run events and results before they are stored or served, and to every log
record. It catches known key formats and configured keys, not everything; Phase 3 replaces
it with the vault and redact/verify/scan/restore.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from collections.abc import Callable, Iterable
from typing import Any

REDACTED = "[REDACTED]"
MIN_SECRET_LEN = 8

KEY_PATTERNS = [re.compile(p) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{8,}",
    r"\brzp_(?:live|test)_[A-Za-z0-9]{8,}",
    r"\bAIza[0-9A-Za-z_\-]{20,}",
    r"\bnvapi-[A-Za-z0-9_\-]{8,}",
    r"\bsk-ant-[A-Za-z0-9_\-]{8,}",
    r"\bsk-[A-Za-z0-9]{20,}",
    r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
)]


class Redactor:
    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values: list[str] = []
        self.set_values(values)

    def set_values(self, values: Iterable[str]) -> None:
        """Replace the configured secret values (call again when connectors change)."""
        found: set[str] = set()
        for value in values:
            if value and len(value) >= MIN_SECRET_LEN:
                found.add(value)
                found.add(base64.b64encode(value.encode()).decode())
        self._values = sorted(found, key=len, reverse=True)  # longest first: no partial leftovers

    def redact_text(self, text: str) -> str:
        for value in self._values:
            if value in text:
                text = text.replace(value, REDACTED)
        for pattern in KEY_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def redact(self, value: Any) -> Any:
        """A copy of `value` with every string inside it redacted (dicts, lists, tuples)."""
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {self.redact(k) if isinstance(k, str) else k: self.redact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(v) for v in value]
        return value


def secret_values_for(connectors: Iterable[Any]) -> set[str]:
    """Current values of every env var the connectors reference, plus NVIDIA_API_KEY (D8)."""
    names = {"NVIDIA_API_KEY"}
    for c in connectors:
        refs = [c.secret_ref] + list(getattr(c.connection, "env_refs", {}).values())
        names.update(ref.split(":", 1)[1] for ref in refs if ref and ref.startswith("env:"))
    return {os.environ[n] for n in names if os.environ.get(n)}


def install_log_redaction(redactor: Redactor) -> Callable[[], None]:
    """Redact every log record at creation, whichever logger or handler it goes to.

    Uses the log-record factory, because logger-level filters miss records propagated from
    child loggers. Returns a function that restores the previous factory.
    """
    previous = logging.getLogRecordFactory()

    def redact_arg(value: Any) -> Any:
        if isinstance(value, str):
            return redactor.redact_text(value)
        if value is None or isinstance(value, (int, float, bool)):
            return value  # keeps %d and friends working
        return redactor.redact_text(str(value))

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        # Redact in place and keep the shape: some formatters (uvicorn's access log) unpack args.
        if isinstance(record.msg, str):
            record.msg = redactor.redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_arg(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact_arg(v) for k, v in record.args.items()}
        if record.exc_info and record.exc_info[0] is not None:
            # formatters reuse exc_text when it is set, so the traceback is printed redacted
            record.exc_text = redactor.redact_text(logging.Formatter().formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
    return lambda: logging.setLogRecordFactory(previous)
