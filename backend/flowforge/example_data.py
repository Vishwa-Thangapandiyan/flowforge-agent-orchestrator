"""Example-data mode (D16): a lively dashboard with no keys and no network.

`flowforge --example` uses its own database (FLOWFORGE_HOME/example.db). It adds example
connectors, swaps every connector's node for an offline ExampleNode of the same type, and seeds
a few runs. Seeded runs and demo runs started from the UI go through the real executor, so
events, critical paths, cache hits, history and savings are genuine. Only the calls are faked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from flowforge.connectors.models import Connector, parse_connector
from flowforge.nodes.base import Node, NodeError, TransientNodeError
from flowforge.schema import Workflow
from flowforge.state import AppState

PROJECT_NAME = "Baby-care shop"
SEED_SCALE = 0.1  # seeded history runs 10x faster than a demo run started from the UI


def _c(data: dict[str, Any]) -> Connector:
    return parse_connector(data)


CONNECTORS: list[Connector] = [_c(d) for d in (
    {"id": "razorpay", "type": "http", "name": "Razorpay", "role": "payments", "slot": "payments", "mode": "test",
     "style": {"color": "#3395FF", "logo": {"type": "letters", "text": "Rz"}}, "rate_limit_rpm": 60,
     "secret_ref": "env:RAZORPAY_KEY",
     "connection": {"base_url": "https://api.razorpay.com/v1", "auth_header": "Authorization", "auth_scheme": "basic"}},
    {"id": "gemini", "type": "llm", "name": "Gemini", "role": "reasoning", "rate_limit_rpm": 15,
     "style": {"color": "#4285F4", "logo": {"type": "letters", "text": "Ge"}}, "secret_ref": "env:GEMINI_API_KEY",
     "connection": {"provider": "openai_compatible", "model": "gemini-3.8-flash",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"}},
    {"id": "claude", "type": "llm", "name": "Claude", "role": "writes code", "fallback": "gemini",
     "style": {"color": "#D97757", "logo": {"type": "letters", "text": "Cl"}}, "secret_ref": "env:ANTHROPIC_API_KEY",
     "connection": {"provider": "anthropic", "model": "claude-opus-5-5"}},
    {"id": "sirius", "type": "local", "name": "Sirius", "role": "security scan",
     "style": {"color": "#0B7A70", "logo": {"type": "letters", "text": "Si"}},
     "connection": {"command": ["sirius", "scan"], "cwd": "."}},
    {"id": "stocks", "type": "mcp", "name": "Stock prices", "role": "market data",
     "style": {"color": "#2E9E5B", "logo": {"type": "letters", "text": "Sp"}},
     "connection": {"command": "uvx", "args": ["stock-prices-mcp"]}},
    {"id": "charts", "type": "local", "name": "Chart script", "role": "draws charts",
     "style": {"color": "#C2398D", "logo": {"type": "letters", "text": "Ch"}},
     "connection": {"command": ["python", "scripts/charts.py"], "cwd": "."}},
    # the apps the example flow map uses (D17)
    {"id": "ollama", "type": "llm", "name": "Ollama", "role": "models on this machine",
     "style": {"color": "#1F2328", "logo": {"type": "letters", "text": "Ol"}},
     "connection": {"provider": "openai_compatible", "base_url": "http://localhost:11434/v1", "model": "llama3.2"}},
    {"id": "inventory", "type": "http", "name": "Inventory API", "role": "stock levels",
     "style": {"color": "#2F6FD6", "logo": {"type": "letters", "text": "IA"}}, "secret_ref": "env:INVENTORY_TOKEN",
     "connection": {"base_url": "https://inventory.example.test", "auth_header": "Authorization",
                    "auth_scheme": "bearer"}},
    {"id": "higgsfield", "type": "http", "name": "Higgsfield", "role": "order pictures",
     "style": {"color": "#2A2A30", "logo": {"type": "letters", "text": "Hf"}}, "secret_ref": "env:HIGGSFIELD_API_KEY",
     "connection": {"base_url": "https://higgsfield.example.test", "auth_header": "Authorization",
                    "auth_scheme": "bearer"}},
    {"id": "gmail", "type": "mcp", "name": "Gmail", "role": "sends email",
     "style": {"color": "#EA4335", "logo": {"type": "letters", "text": "Gm"}},
     "connection": {"command": "npx", "args": ["gmail-mcp"]}},
    {"id": "slack", "type": "mcp", "name": "Slack", "role": "team messages",
     "style": {"color": "#4A154B", "logo": {"type": "letters", "text": "Sl"}},
     "connection": {"command": "npx", "args": ["slack-mcp"]}},
)]


class ExampleNode(Node):
    """Offline stand-in for a connector: sleeps, then returns canned output (or fails)."""

    def __init__(self, type: str, connector_id: str | None, rate_limit_key: str | None, fallback: str | None,
                 default_for_type: bool = False) -> None:
        self.type = type
        self.connector_id = connector_id
        self.rate_limit_key = rate_limit_key
        self.fallback = fallback
        self.default_for_type = default_for_type

    def cacheable_across_runs(self, params: dict[str, Any]) -> bool:
        return False

    async def run(self, params: dict[str, Any]) -> Any:
        await asyncio.sleep(float(params.get("ms", 500)) / 1000)
        if params.get("fail") == "transient":
            raise TransientNodeError(params.get("error", "the server did not answer"))
        if params.get("fail") == "permanent":
            raise NodeError(params.get("error", "the request was refused"))
        return params.get("output", {"kind": "text", "text": "done"})


def example_nodes(state: AppState) -> None:
    """Replace every connector's node (and the type defaults) with an offline ExampleNode."""
    for key, node in list(state.nodes.items()):
        state.nodes[key] = ExampleNode(node.type, node.connector_id, node.rate_limit_key, node.fallback,
                                       node.default_for_type)
    for key in ("llm", "mcp", "http"):
        connector = {"llm": "nim", "mcp": "fetch"}.get(key)
        if connector and connector in state.nodes:
            state.nodes[key] = state.nodes[connector]


def _llm(text: str, prompt: int, completion: int) -> dict[str, Any]:
    return {"kind": "text", "text": text, "model": "example",
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "credits": 0}}


PAYMENTS = {"kind": "table", "rows": [
    {"payment": "pay_••••1a", "amount": "₹1,299", "status": "captured"},
    {"payment": "pay_••••2c", "amount": "₹849", "status": "captured"},
    {"payment": "pay_••••3e", "amount": "₹2,150", "status": "failed"},
]}


def workflows(scale: float = 1.0) -> dict[str, dict[str, Any]]:
    """The example plans, as workflow JSON. `scale` shrinks every step's duration."""
    def ms(value: float) -> int:
        return max(1, round(value * scale))

    def step(id: str, title: str, type: str, connector: str, duration: float, deps: tuple[str, ...] = (),
             **params: Any) -> dict[str, Any]:
        return {"id": id, "description": title, "type": type, "connector": connector, "depends_on": list(deps),
                "estimated_ms": duration, "retries": params.pop("retries", 0),
                "params": {"ms": ms(duration), **params}}

    return {
        "nightly_finance_check": {"id": "nightly_finance_check", "name": "Nightly finance check", "steps": [
            step("scan", "Scan the code", "local", "sirius", 6000,
                 output={"kind": "text", "stdout": "0 new issues, 1 medium (webhook route)", "exit_code": 0}),
            step("payments", "Fetch today's payments", "http", "razorpay", 1000, output={"status": 200, **PAYMENTS}),
            step("prices", "Update stock prices", "mcp", "stocks", 3000,
                 output={"content": "12 prices updated", "structured": {"updated": 12}}),
            step("payments_again", "Fetch payments for the summary", "http", "razorpay", 1000,
                 output={"status": 200, **PAYMENTS}),
            step("charts", "Draw the charts", "local", "charts", 2000, ("payments", "prices"),
                 output={"kind": "text", "stdout": "wrote charts/today.png", "exit_code": 0}),
            step("summary", "Write the summary", "llm", "gemini", 3000, ("scan", "charts", "payments_again"),
                 output=_llm("Revenue ₹4,298 from 3 payments (1 failed). Stock levels steady.", 820, 220)),
        ]},
        "payment_risk_check": {"id": "payment_risk_check", "name": "Payment risk check", "steps": [
            step("payment", "Fetch the captured payment", "http", "razorpay", 800, output={"status": 200, **PAYMENTS}),
            step("risk", "Rate the risk", "llm", "claude", 2200, ("payment",),
                 output=_llm("Order 1042: high risk (new card, large first order).", 300, 112)),
        ]},
        "security_scan": {"id": "security_scan", "name": "Security scan", "steps": [
            step("scan", "Scan the code", "local", "sirius", 6400,
                 output={"kind": "text", "stdout": "0 new issues", "exit_code": 0}),
        ]},
        "swap_razorpay_to_stripe": {"id": "swap_razorpay_to_stripe", "name": "Swap Razorpay to Stripe", "steps": [
            step("docs", "Fetch Stripe lifecycle", "mcp", "fetch", 1800, fail="transient", retries=2,
                 error="could not start its MCP server"),
            step("map", "Map the endpoints", "llm", "claude", 2000, ("docs",), output=_llm("-", 0, 0)),
            step("notes", "Write migration notes", "llm", "claude", 1500, ("map",), output=_llm("-", 0, 0)),
            step("risk", "Write the risk report", "llm", "gemini", 1500, ("map",), output=_llm("-", 0, 0)),
        ]},
    }


# (workflow, how long ago it started)
SEED_RUNS = [
    ("swap_razorpay_to_stripe", timedelta(days=1, hours=2)),
    ("nightly_finance_check", timedelta(hours=17)),
    ("security_scan", timedelta(hours=6)),
    ("payment_risk_check", timedelta(hours=3)),
    ("nightly_finance_check", timedelta(minutes=40)),
]


def install(state: AppState) -> None:
    """Add the example connectors (once) and make every node offline."""
    from flowforge.connectors.runtime import build_node

    for connector in CONNECTORS:
        if state.registry.get(connector.id) is None:
            state.registry.save(connector)
        node, bucket = build_node(connector)
        state.nodes[connector.id] = node
        if bucket is not None and node.rate_limit_key:
            state.rate_limits[node.rate_limit_key] = bucket
    example_nodes(state)


def seed_flow(state: AppState) -> None:
    """The example flow map (D17): the Planner's first map, the project's own edits and the designed layout."""
    from flowforge.flowmap import fixture
    from flowforge.flowmap.service import example_edits

    if state.flows is None:
        return
    if state.flows.first_map() is not None:
        example_edits(state.flows, fixture.EXAMPLE_OVERRIDES, fixture.POSITIONS)


async def seed(state: AppState) -> list[str]:
    """Run the example history once, on an empty database. Returns the new run ids."""
    from flowforge.api.runs import start_run

    if state.storage.list_runs(limit=1):
        return []
    plans = workflows(SEED_SCALE)
    now = datetime.now(UTC)
    run_ids = [start_run(Workflow.model_validate(plans[name]), started_at=now - ago) for name, ago in SEED_RUNS]
    await asyncio.gather(*(state.runs[r].task for r in run_ids if state.runs[r].task), return_exceptions=True)
    return run_ids
