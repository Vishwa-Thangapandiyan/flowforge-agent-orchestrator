"""Tool health, money and time, and app meta for the dashboard (D16).

GET /health/tools   → per connector: status, plain-words label, last OK, last failure, rate left
GET /stats/savings  → time saved vs one at a time, calls skipped by cache, API calls, tokens, credits
GET /meta           → project name, example-data flag, version
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import APIRouter

from flowforge import example_data
from flowforge.api.connectors import connector_steps, secret_status
from flowforge.state import app_state

router = APIRouter()


def ago(iso: str, now: datetime) -> str:
    seconds = max(0, (now - datetime.fromisoformat(iso)).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


@router.get("/health/tools")
def tool_health() -> list[dict[str, Any]]:
    s = app_state()
    now = datetime.now(UTC)
    steps = connector_steps(s)
    out: list[dict[str, Any]] = []
    for connector in s.registry.all():
        items = steps.get(connector.id, [])
        last_ok = next((i for i in items if i["state"] == "succeeded"), None)
        last_fail = next((i for i in items if i["state"] == "failed"), None)
        secret = secret_status(connector, s.example)
        if secret is not None and secret["status"] == "missing":
            status, label = "missing_key", "Key missing"
        elif last_fail and (not last_ok or last_fail["at"] > last_ok["at"]):
            status, label = "failing", f"Failed {ago(last_fail['at'], now)}"
        elif last_ok:
            status, label = "ok", f"OK, {ago(last_ok['at'], now)}"
        else:
            status, label = "idle", "Not used yet"
        rate = None
        if connector.rate_limit_rpm:
            cutoff = (now - timedelta(minutes=1)).isoformat()
            used = sum(i["attempts"] for i in items if i["at"] >= cutoff and not i["cache_hit"])
            rpm = connector.rate_limit_rpm
            rate = {"rpm": int(rpm) if float(rpm).is_integer() else rpm, "used_last_minute": used,
                    "left": max(0, int(rpm - used))}
        out.append({
            "id": connector.id, "name": connector.name, "type": connector.type, "status": status, "label": label,
            "last_ok": last_ok["at"] if last_ok else None,
            "last_failure": last_fail["at"] if last_fail else None,
            "last_error": last_fail["error"] if last_fail else None,
            "rate": rate, "last_test": s.connector_tests.get(connector.id),
        })
    return out


@router.get("/stats/savings")
def savings() -> dict[str, Any]:
    return app_state().storage.savings()


@router.get("/meta")
def meta() -> dict[str, Any]:
    try:
        app_version = version("flowforge")
    except PackageNotFoundError:
        app_version = "0.0.0"
    example = app_state().example
    default = example_data.PROJECT_NAME if example else "My project"
    return {"project": os.getenv("FLOWFORGE_PROJECT_NAME") or default, "example": example, "version": app_version}
