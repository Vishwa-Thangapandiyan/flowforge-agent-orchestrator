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

# The connector catalog (D17): many apps, each with a mock test run. `live` means FlowForge can call it
# today with the user's own key or on their machine; the rest are "Demo only" until their integration lands.
# Fields: id, name, category, connector type, live, one-line description, meta line.
CATEGORIES = {"llm": "LLMs", "pay": "Payments", "dev": "Dev tools", "data": "Data and apps",
              "media": "Media and AI services", "custom": "Your own"}
_CATALOG_ROWS: list[tuple[str, str, str, str, bool, str, str]] = [
    ("nim", "NVIDIA NIM", "llm", "llm", True, "Fast open models on a free tier.", "openai-compatible · 40 rpm free"),
    ("gemini", "Google Gemini", "llm", "llm", True, "Quick general model with a generous free tier.", "openai-compatible · 15 rpm free"),
    ("claude", "Claude", "llm", "llm", True, "Careful writing, code and long documents.", "anthropic · your key"),
    ("openai", "OpenAI", "llm", "llm", True, "GPT models through the standard API.", "openai-compatible · your key"),
    ("ollama", "Ollama", "llm", "llm", True, "Models on your own machine. Nothing leaves it.", "local · port 11434"),
    ("mistral", "Mistral", "llm", "llm", True, "European models, from small to large.", "openai-compatible · your key"),
    ("groq", "Groq", "llm", "llm", True, "Very fast answers from open models.", "openai-compatible · free tier"),
    ("openrouter", "OpenRouter", "llm", "llm", True, "One key for hundreds of models.", "openai-compatible · your key"),
    ("deepseek", "DeepSeek", "llm", "llm", True, "Strong reasoning at a low price.", "openai-compatible · your key"),
    ("perplexity", "Perplexity", "llm", "http", False, "Answers with web sources attached.", "HTTP · search"),
    ("huggingface", "Hugging Face", "llm", "http", False, "Inference for thousands of open models.", "HTTP · inference"),
    ("together", "Together AI", "llm", "llm", False, "Hosted open models and fine-tunes.", "openai-compatible"),
    ("cohere", "Cohere", "llm", "http", False, "Embeddings and reranking for search.", "HTTP · embed, rerank"),
    ("razorpay", "Razorpay", "pay", "http", False, "Payments in India. Starts in test mode.", "HTTP · money moves only behind a gate"),
    ("stripe", "Stripe", "pay", "http", False, "Global payments. Starts in test mode.", "HTTP · money moves only behind a gate"),
    ("paypal", "PayPal", "pay", "http", False, "PayPal wallets and cards.", "HTTP · money moves only behind a gate"),
    ("square", "Square", "pay", "http", False, "In-person and online payments.", "HTTP · money moves only behind a gate"),
    ("adyen", "Adyen", "pay", "http", False, "Payments for large shops.", "HTTP · money moves only behind a gate"),
    ("github", "GitHub", "dev", "mcp", True, "Issues, pull requests and code search.", "MCP · 26 tools"),
    ("sirius", "Sirius", "dev", "local", True, "Your security scanner, run on this machine.", "local · no shell · one folder"),
    ("playwright", "Playwright", "dev", "mcp", True, "Drives a real browser to test pages.", "MCP · 21 tools"),
    ("filesystem", "Filesystem", "dev", "mcp", True, "Reads and writes files in one folder.", "MCP · 11 tools"),
    ("gitlab", "GitLab", "dev", "mcp", False, "Merge requests, pipelines and issues.", "MCP · demo"),
    ("docker", "Docker", "dev", "mcp", False, "Start, stop and inspect containers.", "MCP · demo"),
    ("sentry", "Sentry", "dev", "mcp", False, "Errors and traces from production.", "MCP · demo"),
    ("vercel", "Vercel", "dev", "mcp", False, "Deploys, domains and logs.", "MCP · demo"),
    ("linear", "Linear", "dev", "mcp", False, "Issues and projects.", "MCP · demo"),
    ("jira", "Jira", "dev", "http", False, "Tickets and sprints.", "HTTP · demo"),
    ("fetch", "Fetch", "data", "mcp", True, "Fetches any web page as clean text.", "MCP · uvx mcp-server-fetch"),
    ("postgres", "PostgreSQL", "data", "mcp", True, "Asks your database questions, read-only.", "MCP · 3 tools · read-only"),
    ("supabase", "Supabase", "data", "mcp", False, "Postgres, auth and storage in one.", "MCP · demo"),
    ("mongodb", "MongoDB", "data", "mcp", False, "Document database queries.", "MCP · demo"),
    ("redis", "Redis", "data", "http", False, "Fast key-value cache.", "HTTP · demo"),
    ("notion", "Notion", "data", "mcp", False, "Pages and databases in your workspace.", "MCP · demo"),
    ("slack", "Slack", "data", "mcp", False, "Post and read messages in channels.", "MCP · demo · sending waits for you"),
    ("gmail", "Gmail", "data", "mcp", False, "Send and read email.", "MCP · demo · sending waits for you"),
    ("gdrive", "Google Drive", "data", "mcp", False, "Find and read files in Drive.", "MCP · demo"),
    ("gsheets", "Google Sheets", "data", "http", False, "Read and append rows.", "HTTP · demo"),
    ("airtable", "Airtable", "data", "http", False, "Tables your team already uses.", "HTTP · demo"),
    ("discord", "Discord", "data", "http", False, "Messages and webhooks.", "HTTP · demo"),
    ("telegram", "Telegram", "data", "http", False, "Bots and chat messages.", "HTTP · demo"),
    ("whatsapp", "WhatsApp", "data", "http", False, "Business messages to customers.", "HTTP · demo · sending waits for you"),
    ("twilio", "Twilio", "data", "http", False, "SMS and voice calls.", "HTTP · demo · sending waits for you"),
    ("resend", "Resend", "data", "http", False, "Email from your app.", "HTTP · demo"),
    ("shopify", "Shopify", "data", "http", False, "Products, orders and customers.", "HTTP · demo"),
    ("firebase", "Firebase", "data", "http", False, "App data and auth.", "HTTP · demo"),
    ("higgsfield", "Higgsfield", "media", "http", False, "Images and video from a prompt.", "HTTP · demo"),
    ("elevenlabs", "ElevenLabs", "media", "http", False, "Natural voices and speech.", "HTTP · demo"),
    ("replicate", "Replicate", "media", "http", False, "Run open models by API.", "HTTP · demo"),
    ("stability", "Stability AI", "media", "http", False, "Image generation and editing.", "HTTP · demo"),
    ("runway", "Runway", "media", "http", False, "Video generation and editing.", "HTTP · demo"),
    ("deepgram", "Deepgram", "media", "http", False, "Speech to text, fast.", "HTTP · demo"),
    ("assemblyai", "AssemblyAI", "media", "http", False, "Speech to text and audio insights.", "HTTP · demo"),
    ("custom_mcp", "Any MCP server", "custom", "mcp", True, "A command and its arguments. Tools are found for you.", "MCP · your colour and logo"),
    ("custom_http", "Any HTTP API", "custom", "http", True, "A base URL and the name of its key.", "HTTP · OpenAPI optional"),
    ("custom_local", "Local command", "custom", "local", True, "Any script on your machine. No shell, one folder.", "local · your colour and logo"),
]
CATALOG: list[dict] = [
    {"id": r[0], "name": r[1], "category": r[2], "type": r[3], "live": r[4], "description": r[5], "meta": r[6]}
    for r in _CATALOG_ROWS
]

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
