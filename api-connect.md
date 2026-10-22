# API keys to connect before testing

FlowForge reads every key from a file called **`.env`** in the project root. That file doesn't exist yet and is git-ignored, so your keys never get committed. Create it once:

```bash
cp .env.example .env
```

Never put a key anywhere else: not in code, `connectors.json`, workflow JSON, tests or docs. Connectors only hold the *name* of the variable (`env:NVIDIA_API_KEY`), never the key itself.

## Needed: the one key the app uses by default

| Key | File | Line | What to do |
|---|---|---|---|
| `NVIDIA_API_KEY` | `.env` | **2** | Replace the placeholder `nvapi-xxxxxxxx` with your key, so the line reads `NVIDIA_API_KEY=nvapi-...`. Get a free key at [build.nvidia.com](https://build.nvidia.com). |

Without it, everything except LLM steps still works:
- the tests and the simulated benchmark;
- `diamond_mock` in the app;
- MCP `fetch` steps.

**You need it for:**
- `llm` steps, such as the ones in the `stripe_to_razorpay` example;
- the real benchmark track (`uv run python benchmarks/run_benchmark.py real`).

Lines 4–6 of `.env` (`NIM_RPM`, `NIM_BASE_URL`, `NIM_DEFAULT_MODEL`) are already filled with working defaults, so leave them as they are.

## Optional: only if you connect these providers

These have presets but are **not** connected on first start; only `nim` and `fetch` are. To use one:

1. Add its key as a **new line at the end of `.env`** (from line 7 on, one per line).
2. Add the connector to `~/.flowforge/connectors.json` (see "Connect any provider" in the README). The `secret_ref` there must match the variable name below.

| Key (new line in `.env`) | Provider | Format | Preset defined at |
|---|---|---|---|
| `GEMINI_API_KEY=...` | Gemini | your Google AI Studio key | `backend/flowforge/connectors/presets.py:27` |
| `ANTHROPIC_API_KEY=...` | Claude | your Anthropic API key | `backend/flowforge/connectors/presets.py:32` |
| `RAZORPAY_KEY=...` | Razorpay | `key_id:key_secret` in one value, test-mode keys (`rzp_test_...`) | `backend/flowforge/connectors/presets.py:39` |
| `STRIPE_SECRET_KEY=...` | Stripe | test-mode secret key (`sk_test_...`) | `backend/flowforge/connectors/presets.py:43` |

**No key needed:** Ollama (runs on your machine) and the `fetch` MCP server.

## Check it worked

Restart the app after editing `.env` (`uv run uvicorn flowforge.main:app --reload`). A missing key doesn't crash anything: the step that needs it fails with a clear message naming the variable, for example `NVIDIA_API_KEY is not set`.
