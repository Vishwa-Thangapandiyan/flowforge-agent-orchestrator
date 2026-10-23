"""Known services for the scan, from `connectors.presets.SERVICES` (brands live only there, D10)."""

from __future__ import annotations

import re

from flowforge.connectors.presets import MODEL_PREFIXES, ROUTER_SDKS, SERVICES


def normalize_package(package: str) -> str:
    """Package names compare case-insensitively, with - _ . alike (PyPI vs import names)."""
    return re.sub(r"[-_.]+", "_", package.lower())


_BY_SDK = {normalize_package(sdk): s for s in SERVICES for sdk in s["sdks"]}
_BY_ID = {s["id"]: s for s in SERVICES}
_ROUTERS = {normalize_package(p) for p in ROUTER_SDKS}


def by_id(service_id: str) -> dict | None:
    return _BY_ID.get(service_id)


def by_host(host: str) -> dict | None:
    """The service a host (or host:port) belongs to. A leading "." in the table matches any subdomain."""
    name = host.split(":")[0]
    for s in SERVICES:
        for h in s["hosts"]:
            if host == h or name == h or (h.startswith(".") and name.endswith(h)):
                return s
    return None


def by_sdk(package: str) -> dict | None:
    """The service an imported package stands for: exact, or a sub-module of it (google.genai.types).

    Only dotted sub-modules are trimmed, so a package of your own called `groq_utils` never matches Groq.
    """
    parts = package.split(".")
    for end in range(len(parts), 0, -1):
        service = _BY_SDK.get(normalize_package(".".join(parts[:end])))
        if service is not None:
            return service
    return None


def is_router(package: str) -> bool:
    """An SDK that routes to many LLM providers (litellm): the model name says which."""
    return normalize_package(package.split(".")[0]) in _ROUTERS


def by_model(model: str) -> dict | None:
    """The provider a model name points to: "anthropic/claude-…" or "claude-…" → Claude."""
    name = model.lower()
    for service_id, prefixes in MODEL_PREFIXES.items():
        if name.startswith(prefixes):
            return _BY_ID.get(service_id)
    return None
