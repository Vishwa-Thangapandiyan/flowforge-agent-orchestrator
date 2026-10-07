"""Preset connectors (CLAUDE.md §7.3). The only place in the code where brands appear.

Each preset is an ordinary Connector holding secret *references*. Default models and URLs
come from each provider's own docs (checked 2026-10-07); change them per connector.
Brand colours are approximate tiles with a two-letter monogram, never real logos.
"""

from __future__ import annotations

import os

from flowforge.connectors.models import Connector, parse_connector

DEFAULT_CONNECTORS = ("nim", "fetch")  # seeded on first start: the default llm and mcp (D10)


def _letters(text: str, color: str) -> dict:
    return {"color": color, "logo": {"type": "letters", "text": text}}


PRESETS: dict[str, Connector] = {c.id: c for c in map(parse_connector, [
    {"id": "nim", "type": "llm", "name": "NVIDIA NIM", "role": "free hosted models (default)",
     "style": _letters("Nv", "#76B900"), "rate_limit_rpm": 40, "secret_ref": "env:NVIDIA_API_KEY",
     "connection": {"provider": "openai_compatible", "base_url": "https://integrate.api.nvidia.com/v1",
                    "model": "meta/llama-3.1-8b-instruct"}},
    {"id": "gemini", "type": "llm", "name": "Gemini", "role": "Google's models",
     "style": _letters("Ge", "#4285F4"), "secret_ref": "env:GEMINI_API_KEY",
     "connection": {"provider": "openai_compatible",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "model": "gemini-3.8-flash"}},
    {"id": "claude", "type": "llm", "name": "Claude", "role": "Anthropic's models",
     "style": _letters("Cl", "#D97757"), "secret_ref": "env:ANTHROPIC_API_KEY",
     "connection": {"provider": "anthropic", "model": "claude-opus-5-5"}},
    {"id": "ollama", "type": "llm", "name": "Ollama", "role": "models on your machine",
     "style": _letters("Ol", "#555555"),  # no key: a local server; set model to one you've pulled
     "connection": {"provider": "openai_compatible", "base_url": "http://localhost:11434/v1",
                    "model": "gpt-oss:20b"}},
    {"id": "razorpay", "type": "http", "name": "Razorpay", "role": "payments", "slot": "payments",
     "style": _letters("Rz", "#3395FF"), "mode": "test", "secret_ref": "env:RAZORPAY_KEY",  # "key_id:key_secret"
     "connection": {"base_url": "https://api.razorpay.com/v1", "auth_header": "Authorization",
                    "auth_scheme": "basic"}},
    {"id": "stripe", "type": "http", "name": "Stripe", "role": "payments", "slot": "payments",
     "style": _letters("St", "#635BFF"), "mode": "test", "secret_ref": "env:STRIPE_SECRET_KEY",
     "connection": {"base_url": "https://api.stripe.com/v1", "auth_header": "Authorization",
                    "auth_scheme": "bearer"}},
    {"id": "fetch", "type": "mcp", "name": "Fetch", "role": "reads web pages (default MCP)",
     "style": _letters("Fe", "#8A8A8A"),
     "connection": {"command": "uvx", "args": ["mcp-server-fetch"]}},
])}

# Starting points for the "Custom" choice of each type; the user fills in id, name and connection.
CUSTOM: dict[str, dict] = {
    "llm": {"type": "llm", "connection": {"provider": "openai_compatible", "base_url": "", "model": ""}},
    "mcp": {"type": "mcp", "connection": {"command": "", "args": []}},
    "http": {"type": "http", "connection": {"base_url": "", "auth_header": "Authorization", "auth_scheme": "bearer"}},
    "local": {"type": "local", "connection": {"command": [], "cwd": ""}},
}


def with_env_overrides(connector: Connector) -> Connector:
    """The default NIM connector keeps honouring NIM_RPM, NIM_BASE_URL and NIM_DEFAULT_MODEL (D8, D10)."""
    if connector.id != "nim" or connector.type != "llm":
        return connector
    connection = connector.connection.model_copy(update={
        "base_url": os.getenv("NIM_BASE_URL") or connector.connection.base_url,
        "model": os.getenv("NIM_DEFAULT_MODEL") or connector.connection.model,
    })
    rpm = float(os.getenv("NIM_RPM")) if os.getenv("NIM_RPM") else connector.rate_limit_rpm
    return connector.model_copy(update={"connection": connection, "rate_limit_rpm": rpm})
