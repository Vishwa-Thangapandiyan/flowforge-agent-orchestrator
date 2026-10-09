"""The connector catalog (D17): every app FlowForge knows, whether it is on the map, and a mock test run.

Brands live only in `presets.py`. Test runs here are offline and canned ("mock"): they show what a
real test would do and what the Planner learns from an app, and they never touch a network or a key.
"""

from __future__ import annotations

from typing import Any

from flowforge.connectors.models import Connector
from flowforge.connectors.presets import CATALOG, CATEGORIES

TYPE_NAME = {"llm": "LLM", "mcp": "MCP server", "http": "HTTP API", "local": "Local command"}


def catalog(connectors: dict[str, Connector], on_map: set[str]) -> dict[str, Any]:
    """Catalog entries with a status each, plus connected apps the catalog doesn't list (your own).

    status: `on_map` (the code calls it), `connected` (connected, not in your code) or `none`.
    """
    def status(app_id: str) -> str:
        if app_id in on_map:
            return "on_map"
        return "connected" if app_id in connectors else "none"

    items = [{**entry, "kind": TYPE_NAME[entry["type"]], "status": status(entry["id"])} for entry in CATALOG]
    listed = {entry["id"] for entry in CATALOG}
    own = [{"id": c.id, "name": c.name, "category": "custom", "type": c.type, "kind": TYPE_NAME[c.type],
            "live": True, "description": c.role or "One of your own apps.", "meta": f"{TYPE_NAME[c.type]} · yours",
            "status": status(c.id), "color": c.style.color if c.style else None}
           for c in connectors.values() if c.id not in listed]
    return {"categories": CATEGORIES, "items": items, "own": own}


def find(app_id: str, connectors: dict[str, Connector]) -> dict[str, Any] | None:
    entry = next((e for e in CATALOG if e["id"] == app_id), None)
    if entry is not None:
        return entry
    c = connectors.get(app_id)
    if c is None:
        return None
    return {"id": c.id, "name": c.name, "category": "custom", "type": c.type, "live": True}


def mock_test(entry: dict[str, Any]) -> dict[str, Any]:
    """The canned steps, result and capability summary for one app. No network, no key, no secret text."""
    kind, category, name = entry["type"], entry["category"], entry["name"]
    if category == "pay":
        steps = [("Connect in test mode", "a live key is refused on a test connector"),
                 ("Create a test order", "POST /v1/orders · ₹499.00"), ("Read it back", "GET /v1/orders/{id}")]
        result = '{ "id": "order_example", "amount": 49900, "status": "created" }'
        stats = "0.3 s · test mode, no money moves"
        learns = ["create order", "fetch payment", "refund · always behind a gate"]
    elif kind == "llm":
        steps = [("Connect", "chat/completions"), ("Send a tiny prompt", '"Say hello from FlowForge in one line."'),
                 ("Read the answer", "check the reply and the token count")]
        result, stats = '"Hello from FlowForge. Test run OK."', "0.4 s · 18 tokens"
        learns = ["provider and model", "rate limit", "token counts per call"]
    elif kind == "mcp":
        steps = [("Start the server", "on this machine, as its own process"), ("List its tools", "tools/list"),
                 ("Check the schemas", "arguments are validated before any run")]
        result, stats = "tools listed with their input schemas", "0.6 s · server stopped after"
        learns = ["every tool and its arguments", "which tools only read", "tools that write wait for you"]
    elif kind == "local":
        steps = [("Check the command", "it exists and isn't a shell script"),
                 ("Run it in its folder", "no shell · env passed explicitly"),
                 ("Read the output", "stdout, stderr, exit code")]
        result, stats = "exit 0", "1.2 s"
        learns = ["the command and its arguments", "the folder it may use", "always behind a gate"]
    elif category == "media":
        steps = [("Connect", f"{name} API"), ("Make one sample", '"a soft blue baby blanket"'),
                 ("Save the file", "kept on disk, not in the run log")]
        result, stats = '{ "file": "artifacts/test/sample.png", "width": 1024 }', "0.5 s · example output"
        learns = ["makes images, audio or video", "returns a file", "cost per call, when it reports one"]
    else:
        steps = [("Connect", "GET {base_url}/health"), ("Read its endpoints", "from OpenAPI when you give it"),
                 ("One harmless call", "GET only")]
        result, stats = '{ "ok": true }', "0.2 s"
        learns = ["endpoints and their parameters", "which calls write data (gated)", "key name only, never the value"]
    mode = ("Live: works today with your own key or on your machine. This test run is a mock, so nothing is sent."
            if entry.get("live") else "Demo only: example data, no network, no key needed.")
    return {"id": entry["id"], "name": name, "mock": True, "mode": mode,
            "steps": [{"title": t, "text": x} for t, x in steps], "result": result, "stats": stats, "learns": learns}
