"""Secret references (D10). A connector holds `env:NAME` or `vault:NAME`, never a value.

Phase 1 resolves `env:` from the process environment. `vault:` is reserved for the
Phase 3 vault and refused until then. Errors name the reference, never a value.
"""

from __future__ import annotations

import os
import re

SECRET_REF_PATTERN = r"^(env|vault):[A-Z_][A-Z0-9_]*$"


class SecretRefError(ValueError):
    pass


# A key pasted (and upper-cased) into a "variable name" field still has its key shape (D16).
_KEY_SHAPED_NAME = re.compile(
    r"^(?:(?:SK|RK)_(?:LIVE|TEST)_|RZP_(?:LIVE|TEST)_|AIZA[0-9A-Z_]{16,}|SK_ANT_)", re.IGNORECASE)


def check_ref(ref: str | None) -> str | None:
    """Pydantic-friendly: refuse a reference whose variable name is really a key."""
    if ref is not None and _KEY_SHAPED_NAME.match(ref.split(":", 1)[-1]):
        raise ValueError("that variable name looks like a key; put the key in .env and reference it by name")
    return ref


def resolve_secret(ref: str | None) -> str | None:
    """The secret value for `ref`, or None when no secret is configured."""
    if ref is None:
        return None
    scheme, _, name = ref.partition(":")
    if scheme == "vault":
        raise SecretRefError(f"secret '{ref}' needs the vault, which arrives in Phase 3; use env:{name} for now")
    if scheme != "env" or not name:
        raise SecretRefError(f"unsupported secret reference '{ref}'")
    value = os.environ.get(name)
    if not value:
        raise SecretRefError(f"{name} is not set (referenced as '{ref}'); add it to .env")
    return value


def resolve_env(env: dict[str, str], env_refs: dict[str, str]) -> dict[str, str]:
    """Plain env values plus resolved secret env values (D12, D13)."""
    resolved = dict(env)
    for var, ref in env_refs.items():
        value = resolve_secret(ref)
        if value is not None:
            resolved[var] = value
    return resolved
