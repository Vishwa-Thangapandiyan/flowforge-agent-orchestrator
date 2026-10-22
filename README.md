# FlowForge

**An LLMOps tool for apps that already use AI: a map of how your app's LLM, MCP and API calls fit together, and a scheduler that runs them.**

You connect the apps your project uses (LLMs, MCP servers, HTTP APIs, local commands). The **Planner** reads your repo and runs the app in test mode, then draws the flow on the home page: the calls, the decisions, what runs together, the retries and fallbacks, and a gate in front of anything that moves money or sends a message. Only apps your code actually calls go on the map, and every block cites its evidence (a `file:line` or a traced call). You read the map, edit it if you want (your edits never touch your code), and re-check it when the code changes.

Underneath, FlowForge runs workflows as a DAG: it orders the steps, runs independent ones together under rate limits, caches repeat calls, and (on the roadmap) holds the secrets and pauses risky steps for a human to approve.

What makes it different: **it knows which chain of steps is the bottleneck and schedules around it.**

- orders steps with **topological sort** (Kahn's), and reports the exact loop if there is a cycle
- finds the bottleneck chain with a **longest-path DP** (critical path), predicted before the run and measured after it
- runs independent steps concurrently under limited resources (`k` slots + per-provider rate limits) using **critical-path list scheduling** (HLFET), which is within `(2 − 1/k)` of optimal (Graham's bound)
- makes duplicate calls only once through **memoization** (single-flight in-run cache + a safe persistent cache)

**Free by default.** The default install, the tests and CI need no paid service: LLM steps use NVIDIA NIM's free tier, and local models (Ollama) are planned. Paid providers will work if you bring your own key, but are never needed.

**Local first.** One process, SQLite, files on disk. No cloud account, no Docker, no Redis.

> FlowForge started as a Design and Analysis of Algorithms course project. That version is frozen on the [`DAA`](../../tree/DAA) branch. `main` is the product.

## Quick start

You need **[uv](https://docs.astral.sh/uv/)** (it installs Python for you) and **[Node.js](https://nodejs.org/) 20 or newer** for the dashboard.

```bash
git clone https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator.git
cd flowforge-agent-orchestrator
uv sync                                   # Python ≥ 3.12 and dependencies, into .venv
cd frontend && npm ci && npm run build && cd ..
uv run flowforge --example                # opens http://127.0.0.1:8000: a sample app's maps, no keys needed
```

`uv run flowforge` (without `--example`) runs on your own data. Example data lives in its own database, so the two never mix.

### Map your own repo

```bash
uv run flowforge scan path/to/your/repo     # what it depends on, as JSON: nothing stored, nothing sent
uv run flowforge --repo path/to/your/repo   # opens its dependency map; add --replace to switch folders
```

The scan is plain code: it reads your files, never runs them, and sends nothing to anyone, AI included. Every dependency (LLM, MCP server, HTTP API, local command) comes with the `file:line` that shows it, and code excerpts are stored with known key formats masked.

Then press **Check now**. Every dependency gets one harmless check, and the map turns green, amber or red:
- **APIs:** one request, with no key, cookie or query.
- **LLMs:** their model list is read.
- **MCP servers:** each is started in your repo folder, without your environment variables, asked for its tools, then stopped.
- **Local programs:** only looked for, never run.

Starting an MCP server runs code, so the first check lists exactly what will start and waits for your yes. When something is down, the **Checks** page says why, in the server's own words, and the likely fix.

### See the order your app runs in

Switch the map to **Flow**. FlowForge reads your Python (by its syntax tree, never running it) and draws the order your code calls its dependencies: which call waits for which, the `if`s that choose, and where the code stops early. Every block and line points to its `file:line`.

- **The critical path** is the chain that sets the total time, weighted by the latencies your last check measured (LLMs are estimates, and say so).
- **Faster** compares "as written" (one call after another) with "could be", and lists the calls that don't need each other's results. **Show the change** writes out the `asyncio.gather` (now → could be, ready to copy) when it's safe; **Copy prompt for your coding agent** hands the rest to Claude Code, Codex or any agent. FlowForge never edits your code.
- **Watch it run** plays the could-be schedule; pointing at a block lights up its path. Five map styles: Studio, Boxed, Blueprint, Metro, Soft.

Dart and JS/TS flows come next; the dependency map already covers them.

### Use it from your coding agent

FlowForge is also an **MCP server**, so Claude Code, Codex or Antigravity can ask it about your app and then make the change themselves. Open **Connect agent** in the dashboard: it gives you the one line (or config block) for your agent, with the paths filled in. For Claude Code it looks like:

```bash
claude mcp add flowforge -- uv --directory /path/to/flowforge run flowforge mcp --repo /path/to/your/app
```

Your agent gets five read-only tools: `get_map`, `get_flow`, `get_advice`, `check_health` and `what_changed`. Every answer is masked (key values never appear), FlowForge never edits your code, and a check starts an MCP server only after you said yes to it on the Checks page. FlowForge needs no AI of its own for any of this.

### Send someone the map

**Export** on the map opens the **MCP Map**: a standard picture of an app's MCP architecture (lanes by kind, time left to right, one shape per kind, a title block and a key; rules in [docs/mcp-map.md](docs/mcp-map.md)). Download it as **SVG** (documents), **PNG 2×** (slides), **PDF** (reports, A4 landscape), copy it as **Mermaid** (GitHub draws it in a README or pull request), or save the **Flow JSON** behind it. It's all made in your browser, from data whose key formats were already masked.

### On Windows (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # uv, once
winget install OpenJS.NodeJS.LTS                                                      # Node, once
git clone https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator.git
cd flowforge-agent-orchestrator
uv sync
cd frontend; npm ci; npm run build; cd ..
uv run flowforge --example
```

- **Inside OneDrive** (Desktop or Documents is often synced), OneDrive can lock files while uv installs. Set `$env:UV_LINK_MODE = "copy"` first, and simply re-run `uv sync` if it reports "Access is denied".
- **Behind antivirus or a company proxy** that inspects HTTPS, uv may report `invalid peer certificate`. Use `uv sync --native-tls`.
- **Keep the folder path short** (for example `C:\code\flowforge`). Some dependency files have long names, and Windows refuses paths over 260 characters unless [long paths are enabled](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation). The symptom is a `ModuleNotFoundError` from inside `.venv` when FlowForge starts.

### Developing the dashboard

```bash
cd frontend
npm run dev        # API with example data on :8000 + the dashboard on http://localhost:5173, both reload on change
npm test           # dashboard tests (offline)
```

```bash
uv run pytest      # backend tests, offline: no key, no network
uv run ruff check  # lint
```

The API works on its own too, for scripts and CI: `uv run uvicorn flowforge.main:app --reload`, then `POST /runs` with workflow JSON (see below). The original status page is still at `/classic`.

To use real LLM steps, `cp .env.example .env` and add a free `NVIDIA_API_KEY` from [build.nvidia.com](https://build.nvidia.com); [api-connect.md](api-connect.md) lists every key and where it goes. MCP steps use `mcp-server-fetch`, which `uvx` downloads on first use.

## The dashboard

| Page | What it shows |
|---|---|
| **Flow map** (home) | Your app's dependency map on a canvas: pan, zoom, drag, search, minimap. Every block is something the code uses (an LLM, an MCP server, an API, a local program), with its evidence (`file:line` with the code). Dashed blocks were only mentioned, never called. **Scan a folder** maps another folder; **Re-scan the repo** shows what changed. "As scanned / With my edits" switches between the scan and your edits. **Flow** shows the order the code calls them, the critical path and the **Faster** panel; **Style** picks one of five looks |
| **MCP Map** (Export) | The map to send: SVG, PNG, PDF, Mermaid or Flow JSON |
| **Checks** | Check now, each dependency's verdict, why it's down and the likely fix, and the history |
| **Connect agent** | The set-up for Claude Code, Codex or Antigravity; what your agent gets from this repo (dependencies, health, time, ways to be faster); and, once connected, what it asked |
| **How the Planner drew it** | The analysis replayed: read the repo, run the app in test mode, trace the calls, draft, check. What it read, what it dropped and why |
| **Re-check** | What changed in your repo since the last map: added, changed, removed, and conflicts with your edits. You pick what to take; the old version stays listed |
| **Connectors** | A catalog of 56 apps with search and categories, honest **Live** / **Demo only** badges, and a mock test run for every one. Apps you connected but your code doesn't call wait here, off the map |
| **Connector page** | One app's connection (keys shown only as *configured*, *missing* or *example*), what it has done, and its recent activity |
| **Add an app** | LLM, MCP server, HTTP API or local command; colour and logo; a live preview; and exactly what gets saved, with no secrets |
| **Workflow runs** (under Checks, advanced) | Money and time saved, and every scheduled run: live bars with the slowest chain outlined, outputs, and why a failed run failed |
| Security | A placeholder until security findings (Phase 7) |

Both maps are drawn by plain code from your repo, with no AI, and nothing on them is drawn by hand. Edits on the map change how FlowForge maps your app, never your code.

## Connect any provider

Each app you connect is a **connector**: an LLM, an MCP server, an HTTP API or a local command. Two are ready on first start: `nim` (the default LLM) and `fetch` (the default MCP server). Add more in `~/.flowforge/connectors.json` (or `$FLOWFORGE_HOME/connectors.json`); it's checked and loaded at start-up:

```json
[
  { "id": "gemini", "type": "llm", "name": "Gemini", "rate_limit_rpm": 15,
    "secret_ref": "env:GEMINI_API_KEY",
    "connection": { "provider": "openai_compatible",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "model": "gemini-3.8-flash" } },
  { "id": "claude", "type": "llm", "name": "Claude", "fallback": "gemini",
    "secret_ref": "env:ANTHROPIC_API_KEY",
    "connection": { "provider": "anthropic", "model": "claude-opus-5-5" } },
  { "id": "scripts", "type": "local", "name": "My scripts",
    "connection": { "command": ["python", "tools/report.py"], "cwd": "/home/me/project" } }
]
```

Then point a step at it with `"connector": "gemini"`. Steps without a `connector` use their type's default, so existing workflows run unchanged.

- **Keys stay out of the file.** A connector holds a reference such as `env:GEMINI_API_KEY`, and the key lives in `.env`. Connectors and API responses show only the reference; HTTP connectors send the key only to their own `base_url` and redact it from error messages. (Full secret handling, the vault and redaction, is Phase 4.)
- **Each connector gets its own rate limit and cache**, so two providers never share a budget or an answer.
- **`fallback`** names another connector of the same type, tried only after every retry failed with a transient error (rate limit, 5xx, timeout).
- **MCP servers** have their tools discovered (`GET /connectors/{id}/tools`), and every call is checked against the tool's schema before it is sent.
- **Local commands** never run through a shell, stay inside their folder and see only the environment you give them (plus the few variables the OS needs to start a program).

Ready-made presets: NVIDIA NIM, Gemini, Claude, Ollama, Razorpay, Stripe and the fetch MCP server (`backend/flowforge/connectors/presets.py`). The rules are in [DECISIONS.md](DECISIONS.md) D10, D12 and D13.

## Status and roadmap

| Phase | What | Status |
|---|---|---|
| — | Scheduler core: five policies, caches, retries, SSE run stream, status page, benchmarks | **Done** |
| 1 | Any LLM (OpenAI-compatible + Anthropic), any MCP server with tool discovery, `local` command steps, connector registry, ruff + CI | **Done** |
| 2 | Dashboard v1: live run, tool health, money and time, run history, add/edit apps, example data | **Done** |
| 3 | The flow map: canvas, step panel and edits, replay, re-check diff, connector catalog | **Done** |
| 4 | Repo scan: every dependency with its `file:line`, no LLM | **Done** |
| 5 | Health checks: Check now, why it's down, the Checks page | **Done** |
| 6 | Flow order from Python code, the critical path, "run these together" with the change written out, map styles, the MCP Map export | **Done** |
| 6b | Flow order from Dart and JS/TS | Next |
| 7 | Security findings: hard-coded keys, `http://` APIs, risky MCP configs | Planned |
| 8 | Launch: docs, demo, `pip install` | Planned |
| 9 | CLI agent and a desktop app (Tauri) | Planned |
| 10 | V2: a local coding agent adds a dependency on a branch, for you to approve | Later |
| 11 | FlowForge's own small local model | Later |

The full roadmap with acceptance criteria is in [CLAUDE.md](CLAUDE.md) §5.

### Security (Phase 4, not built yet)

The promise, once Phase 4 ships: API keys and other recognised secrets are never sent to an LLM, never written to logs, run history, cache, workflow JSON or the dashboard, and never committed to git. Detection catches **known key formats** plus high-entropy values in key-like names, not everything. The rest of your code and data still goes to whichever LLM you choose; for private code, use a local model. **Until then, keys live only in your `.env`** (git-ignored).

## API

| Endpoint | Purpose |
|---|---|
| `POST /validate` | Workflow JSON → run order, levels, predicted critical path, warnings. Returns 422 with the cycle, schema error, unknown connector or wrong MCP call |
| `POST /runs?policy=critical_path&use_cache=true` | Starts a run in the background → `{"run_id", "warnings"}` |
| `GET /runs?status=&limit=&before=` | Run history, newest first |
| `GET /runs/{id}` | Status, the full result and the plan outline (kept after a restart) |
| `GET /runs/{id}/events` | Event stream (SSE): live while running, replayed from storage afterwards |
| `POST /runs/{id}/stop` | Stops a running run |
| `GET /connectors`, `GET /connectors/{id}` | Connectors, with key status `set` / `missing` / `example`, never values |
| `POST /connectors`, `PUT /connectors/{id}`, `DELETE /connectors/{id}` | Add, edit, remove (apps from `connectors.json` are read-only) |
| `POST /connectors/{id}/logo`, `GET /connectors/{id}/logo` | PNG, JPEG or WebP logo, up to 1 MB |
| `POST /connectors/{id}/test` | One harmless check (MCP and local apps) |
| `GET /connectors/{id}/activity`, `GET /connectors/{id}/tools` | What an app has done; an MCP server's tools |
| `GET /health/tools`, `GET /stats/savings`, `GET /meta`, `GET /presets` | Tool health, money and time, app info, ready-made apps |
| `GET /workflows`, `GET /workflows/{name}` | The example workflows |
| `GET /flow?layer=mine\|planner` | The flow map: blocks, lines, positions, critical path, your edits |
| `PUT /flow/positions` | Save where blocks sit |
| `POST /flow/overrides`, `DELETE /flow/overrides/{id}`, `DELETE /flow/nodes/{id}/overrides` | Edit the map (swap an app, rename, hide, confirm, add a step or line), undo one edit, reset a block. Gates can't be hidden |
| `GET /flow/trace`, `GET /flow/analysis` | The traced test order the map replays; how the Planner drew the map |
| `POST /flow/recheck`, `GET /flow/versions`, `GET /flow/versions/{n}`, `POST /flow/versions/{n}/accept\|discard` | Re-check: a new version and its diff; take what you pick |
| `GET /catalog`, `POST /catalog/{id}/test` | The connector catalog with each app's status; a mock test run (offline) |

Runs, step results and events are stored in SQLite after known key formats and your configured keys are replaced with `[REDACTED]`. A browser asking for HTML on a path like `/runs/abc` gets the dashboard; everything else gets JSON.

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

Step types are `llm`, `http`, `mcp`, `local` and `mock`. Optional fields per step are `connector`, `estimated_ms`, `timeout_s`, `retries` (default 2), `cache` (`true`/`false`) and `description`. A step may only reference outputs of steps in its own `depends_on`. The full rules are in [DECISIONS.md](DECISIONS.md).

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
| `backend/flowforge/nodes/` | `llm` (any provider), `http`, `mcp`, `local`, `mock` step types |
| `backend/flowforge/connectors/` | Connector models, secret references, presets and the catalog, registry |
| `backend/flowforge/scan/` | The repo scan: dependencies and their evidence, by plain code |
| `backend/flowforge/checks/` | One harmless health check per dependency |
| `backend/flowforge/flow/` | Flow order from Python code: the calls, the `if`s, the critical path weights, the advice |
| `backend/flowforge/flowmap/` | The flow map: Flow JSON models, validation and code-inserted gates, the Planner interface and its example fixture, re-check diff |
| `backend/flowforge/schema.py`, `templating.py`, `storage.py` | Validation, `{{steps.x.output}}` templates, SQLite |
| `backend/flowforge/main.py`, `api/` | The API: start-up wiring, runs, connectors, health and savings |
| `backend/flowforge/security/logfilter.py` | Redaction of keys before anything is stored, streamed or logged |
| `backend/flowforge/example_data.py`, `cli.py` | Example-data mode and the `flowforge` command |
| `frontend/` | The dashboard (Vite + React + TypeScript; the map uses React Flow and dagre); the old status page is `frontend/classic.html` |
| `backend/workflows/` | Example workflows |
| `benchmarks/` | Random DAG generator + benchmark runner |

Tests are in `backend/tests/` and never touch the network. They include property tests (hypothesis) that check the topological order, the levels and the critical-path DP against brute force on random DAGs, and the scheduler's invariants under every policy.

## Docs

- [DECISIONS.md](DECISIONS.md): every design decision and its reason (D1–D9 for the scheduler core, D10–D18 for connectors, gates, MCP, local commands, planning, the dashboard, run history and the flow map, D19–D26 for the repo scan, health checks, flow order and the MCP Map)
- [docs/mcp-map.md](docs/mcp-map.md): the MCP Map's six rules and its export formats
- [CLAUDE.md](CLAUDE.md): roadmap, security spec, data model and working rules
- [docs/design/](docs/design/README.md): the design artboards; `flow-map-artboards/` is the current spec for the flow map
- [AGENTS.md](AGENTS.md): the build workflow for coding agents, and the processes deployed at runtime
- [FlowForge_V1_Plan.md](FlowForge_V1_Plan.md): the original course-project plan (complete)
- [FlowForge_Server_Orchestrator_Plan.md](FlowForge_Server_Orchestrator_Plan.md): Phase 7, server + workers

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, the checks a pull request must pass (offline tests and ruff, on Linux and Windows in CI) and the rules that keep FlowForge safe and free.

## Licence

[MIT](LICENSE)
