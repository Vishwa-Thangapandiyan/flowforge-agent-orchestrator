"""Known services for the scan, from `connectors.presets.SERVICES` (brands live only there, D10)."""

from __future__ import annotations

import re

from flowforge.connectors.presets import SERVICES


def normal(package: str) -> str:
    """Package names compare case-insensitively, with - _ . alike (PyPI vs import names)."""
    return re.sub(r"[-_.]+", "_", package.lower())


_BY_SDK = {normal(sdk): s for s in SERVICES for sdk in s["sdks"]}


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
        service = _BY_SDK.get(normal(".".join(parts[:end])))
        if service is not None:
            return service
    return None
