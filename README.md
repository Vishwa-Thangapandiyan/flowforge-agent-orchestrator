# FlowForge

**The scheduler layer for agent workflows, plus a dashboard to connect, watch and control them.**

You connect apps (LLMs, MCP servers, HTTP APIs, local commands) to one project. FlowForge runs them as a DAG: it orders the steps, runs independent ones together under rate limits, caches repeat calls, and (on the roadmap) holds the secrets and pauses risky steps for a human to approve.

What makes it different: **it knows which chain of steps is the bottleneck and schedules around it.**

- orders steps with **topological sort** (Kahn's), and reports the exact loop if there is a cycle
- finds the bottleneck chain with a **longest-path DP** (critical path), predicted before the run and measured after it
- runs independent steps concurrently under limited resources (`k` slots + per-provider rate limits) using **critical-path list scheduling** (HLFET), which is within `(2 − 1/k)` of optimal (Graham's bound)
- makes duplicate calls only once through **memoization** (single-flight in-run cache + a safe persistent cache)

**Free by default.** The default install, the tests and CI need no paid service: LLM steps use NVIDIA NIM's free tier, and local models (Ollama) are planned. Paid providers will work if you bring your own key, but are never needed.

**Local first.** One process, SQLite, files on disk. No cloud account, no Docker, no Redis.

> FlowForge started as a Design and Analysis of Algorithms course project. That version is frozen on the [`DAA`](../../tree/DAA) branch. `main` is the product.

## Quickstart (3 commands)

```bash
uv sync                                     # Python ≥ 3.12, installs into .venv
uv run pytest                               # optional: the full suite, offline, no key needed
uv run uvicorn flowforge.main:app --reload  # open http://localhost:8000
```

On the page, pick `diamond_mock` (runs with no key), choose a policy and hit **Run**. Steps colour live as they run (Server-Sent Events), the critical path is highlighted, and clicking a step shows its output.

To use real LLM steps, `cp .env.example .env` and add a free `NVIDIA_API_KEY` from [build.nvidia.com](https://build.nvidia.com). MCP steps use `mcp-server-fetch`, which `uvx` downloads on first use.

## Status and roadmap

| Phase | What | Status |
|---|---|---|
| — | Scheduler core: five policies, caches, retries, SSE run stream, status page, benchmarks | **Done** |
| 1 | Any LLM (OpenAI-compatible + Anthropic), any MCP server with tool discovery, `local` command steps, connector registry, ruff + CI | **In progress** |
| 2 | Dashboard v1: hub map, live run, tool health, money and time; persisted run history | Planned |
| 3 | Connectors with forms, secrets vault, redaction, security tab | Planned |
| 4 | Human approval gates; swap one app for another (e.g. Razorpay → Stripe) on a git branch | Planned |
| 4b | AI-suggested tasks and workflow rewiring (the LLM proposes, a human approves) | Planned |
| 5 | Control plane on a home server, workers on a laptop, over Tailscale ([plan](FlowForge_Server_Orchestrator_Plan.md)) | Planned, after Phase 3 |
| 6 | Visual builder for non-developers | Later |

The full roadmap with acceptance criteria is in [CLAUDE.md](CLAUDE.md) §5.

### Security (Phase 3, not built yet)

The promise, once Phase 3 ships: API keys and other recognised secrets are never sent to an LLM, never written to logs, run history, cache, workflow JSON or the dashboard, and never committed to git. Detection catches **known key formats** plus high-entropy values in key-like names, not everything. The rest of your code and data still goes to whichever LLM you choose; for private code, use a local model. **Until then, keys live only in your `.env`** (git-ignored).

## API

| Endpoint | Purpose |
|---|---|
| `POST /validate` | Workflow JSON → run order, levels, predicted critical path. Returns 422 with the cycle or schema error |
| `POST /runs?policy=critical_path&use_cache=true` | Starts a run in the background → `{"run_id"}` |
| `GET /runs/{id}` | Status and the full result |
| `GET /runs/{id}/events` | Live event stream (SSE) |
| `GET /workflows`, `GET /workflows/{name}` | The example workflows |

Runs are currently kept in memory, so a server restart forgets them (persisted in Phase 2).

## Workflow format

```json
{
  "id": "example",
  "max_concurrency": 4,
  "type_concurrency": { "llm": 3 },
  "steps": [
    { "id": "fetch", "type": "http", "params": { "url": "https://docs.stripe.com/api/payment_intents.md" } },
    { "id": "summarize", "type": "llm", "depends_on": ["fetch"],
      "params": { "prompt": "Summarize: {{steps.fetch.output.body}}", "temperature": 0 } }
  ]
}
```

Step types today are `llm`, `http`, `mcp` and `mock`. Optional fields per step are `estimated_ms`, `timeout_s`, `retries` (default 2), `cache` (`true`/`false`) and `description`. A step may only reference outputs of steps in its own `depends_on`. The full rules are in [DECISIONS.md](DECISIONS.md).

## Scheduling policies and benchmarks

Five policies, selectable per run, so the scheduler can be compared against the obvious alternatives:

| Policy | Behaviour |
|---|---|
| `sequential` | one at a time, topological order |
| `levels` | BFS layers, wait for each layer to finish |
| `greedy` | unlimited concurrency |
| `fifo` | `k` slots, first ready first served |
| `critical_path` | `k` slots, longest remaining chain first (**default**) |

On 200 random DAGs with `k = 4`, `critical_path` finishes 8.3% ± 1.1% sooner than `fifo` and sits effectively at the theoretical lower bound. Full results: [benchmarks/RESULTS.md](benchmarks/RESULTS.md).

```bash
# Simulated track: random DAGs with mock steps. Free and offline; 100 graphs take about 5 minutes
uv run python benchmarks/run_benchmark.py sim --graphs 500 --k 4

# Real track: an example workflow against real NIM + HTTP + MCP. Needs NVIDIA_API_KEY
uv run python benchmarks/run_benchmark.py real
```

Both tracks run every policy with the cache off and on, and write CSV plus a markdown summary to `benchmarks/results/`. The real track saves measured call latencies, and later simulated runs sample their step durations from them.

## Layout

| Path | What |
|---|---|
| `backend/flowforge/scheduler/graph.py` | DAG, Kahn's topological sort, cycle reporting, levels |
| `backend/flowforge/scheduler/critical_path.py` | Critical path DP, bottom levels (priorities), lower bound |
| `backend/flowforge/scheduler/durations.py` | Duration estimates (EWMA history → estimate → default) |
| `backend/flowforge/scheduler/executor.py` | The list scheduler: slots, priority heap, retries, timeouts, failure handling, the five policies |
| `backend/flowforge/scheduler/rate_limit.py` | Async token bucket |
| `backend/flowforge/scheduler/cache.py` | Single-flight memo + persistent cache |
| `backend/flowforge/nodes/` | `llm` (NIM), `http`, `mcp`, `mock` step types |
| `backend/flowforge/schema.py`, `templating.py`, `storage.py` | Validation, `{{steps.x.output}}` templates, SQLite |
| `backend/flowforge/main.py`, `frontend/index.html` | API + live status page |
| `backend/workflows/` | Example workflows |
| `benchmarks/` | Random DAG generator + benchmark runner |

Tests are in `backend/tests/` and never touch the network. They include property tests (hypothesis) that check the topological order, the levels and the critical-path DP against brute force on random DAGs, and the scheduler's invariants under every policy.

## Docs

- [DECISIONS.md](DECISIONS.md): every design decision and its reason (D1–D9, new ones continue from D10)
- [CLAUDE.md](CLAUDE.md): roadmap, security spec, data model and working rules
- [AGENTS.md](AGENTS.md): the build workflow for coding agents, and the processes deployed at runtime
- [FlowForge_V1_Plan.md](FlowForge_V1_Plan.md): the original course-project plan (complete)
- [FlowForge_Server_Orchestrator_Plan.md](FlowForge_Server_Orchestrator_Plan.md): Phase 5, server + workers

## Contributing

Issues and PRs are welcome. Work happens on a branch per phase (`feat/phase-N-<name>`) with a PR into `main`; never against `DAA`. Before opening a PR: `uv run pytest` is green offline, new behaviour has tests including a failure case, and design changes get a new D-numbered entry in `DECISIONS.md` first. Never put a real API key in code, tests, fixtures or docs. A fuller `CONTRIBUTING.md` arrives with Phase 1.

## Licence

[MIT](LICENSE)
