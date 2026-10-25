"""The whole API answers only to this machine (D47): every request must name it in its Host (against DNS rebinding),
and every change that carries an Origin must come from it (against another site's form). One ASGI middleware in
front of everything, so a new route can't forget it."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
SAFE = frozenset({"GET", "HEAD", "OPTIONS"})
REFUSED = json.dumps({"detail": "FlowForge answers only to this machine: open it at http://localhost."}).encode()


def allowed_hosts() -> set[str]:
    """This machine's names, the address chosen with --host (FLOWFORGE_HOST, unless it means every address), and
    FLOWFORGE_ALLOWED_HOSTS (tests: Starlette's TestClient is "testserver")."""
    names = set(LOOPBACK)
    chosen = os.getenv("FLOWFORGE_HOST", "").strip().strip("[]").lower()
    if chosen and chosen not in ("0.0.0.0", "::"):
        names.add(chosen)
    names |= {h.strip().lower() for h in os.getenv("FLOWFORGE_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return names


def _hostname(value: str) -> str | None:
    try:
        return urlsplit(value if "//" in value else f"//{value}").hostname
    except ValueError:
        return None


def refused(method: str, headers: dict[str, str]) -> bool:
    """Does this request come from somewhere other than this machine?"""
    names = allowed_hosts()
    if _hostname(headers.get("host", "")) not in names:
        return True
    origin = headers.get("origin")
    return method not in SAFE and origin is not None and _hostname(origin) not in names


class LocalOnly:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            if refused(scope.get("method", "GET").upper(), headers):
                if scope["type"] == "http":
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": REFUSED})
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)
