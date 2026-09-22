# FlowForge

A workflow scheduler for LLM, MCP and HTTP steps, built as a DAA project. You describe a workflow as JSON steps with dependencies. FlowForge then:

- orders the steps with **topological sort** (Kahn's), and reports the exact loop if there is a cycle
- finds the bottleneck chain with a **longest-path DP** (critical path)
- runs independent steps concurrently under limited resources (`k` slots + an API rate limit) using **critical-path list scheduling** (HLFET), which is within `(2 − 1/k)` of optimal (Graham's bound)
- makes duplicate calls only once through **memoization** (single-flight in-run cache + a safe persistent cache)

Everything is free: the LLM steps use NVIDIA NIM's free tier.

- Plan: [FlowForge_V1_Plan.md](FlowForge_V1_Plan.md)
- Design decisions and the reasons for them: [DECISIONS.md](DECISIONS.md)
- Future scope (V2, two machines): [FlowForge_Server_Orchestrator_Plan.md](FlowForge_Server_Orchestrator_Plan.md)

## Setup

```bash
uv sync                      # installs dependencies + dev tools into .venv
cp .env.example .env         # add your free NVIDIA_API_KEY from build.nvidia.com
uv run pytest                # all tests run offline: no key, no network
```

The MCP steps use `mcp-server-fetch`, which `uvx` downloads on first use.

## Run the app

```bash
uv run uvicorn flowforge.main:app --reload
# open http://localhost:8000: pick an example, choose a policy, hit Run
```

The page draws the workflow by level, colours each step live as it runs (over Server-Sent Events), highlights the critical path, and shows a step's output when you click it.

| Endpoint | Purpose |
|---|---|
| `POST /validate` | Workflow JSON → run order, levels, predicted critical path. Returns 422 with the cycle or schema error |
| `POST /runs?policy=critical_path&use_cache=true` | Starts a run in the background → `{"run_id"}` |
| `GET /runs/{id}` | Status and the full result |
| `GET /runs/{id}/events` | Live event stream (SSE) |
| `GET /workflows`, `GET /workflows/{name}` | The example workflows |

## Benchmarks

```bash
# Simulated track: random DAGs with mock steps. Free and offline; 100 graphs take about 5 minutes
uv run python benchmarks/run_benchmark.py sim --graphs 500 --k 4

# Real track: an example workflow against real NIM + HTTP + MCP. Needs NVIDIA_API_KEY
uv run python benchmarks/run_benchmark.py real
```

Latest results: [benchmarks/RESULTS.md](benchmarks/RESULTS.md).

Both tracks compare five policies (`sequential`, `levels`, `greedy`, `fifo`, `critical_path`), each with the cache off and on. Results go to `benchmarks/results/` as CSV plus a markdown summary. The real track saves measured call latencies, and later simulated runs sample their step durations from them.

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

Step types are `llm`, `http`, `mcp` and `mock`. Optional fields per step are `estimated_ms`, `timeout_s`, `retries` (default 2), `cache` (`true`/`false`) and `description`. The full rules are in [DECISIONS.md](DECISIONS.md).

## Layout

| Path | What | Owner |
|---|---|---|
| `backend/flowforge/scheduler/graph.py` | DAG, Kahn's topological sort, cycle reporting, levels | A |
| `backend/flowforge/scheduler/critical_path.py` | Critical path DP, bottom levels, lower bound | A |
| `backend/flowforge/scheduler/durations.py` | Duration estimates (EWMA history → estimate → default) | A |
| `backend/flowforge/scheduler/executor.py` | The list scheduler: slots, priority heap, retries, timeouts, failure handling | B |
| `backend/flowforge/scheduler/rate_limit.py` | Async token bucket | B |
| `backend/flowforge/scheduler/cache.py` | Single-flight memo + persistent cache | B |
| `backend/flowforge/nodes/` | `llm` (NIM), `http`, `mcp`, `mock` step types | C |
| `backend/flowforge/main.py`, `frontend/index.html` | API + live status page | C |
| `benchmarks/` | Random DAG generator + benchmark runner | C |
| `backend/flowforge/schema.py`, `templating.py`, `storage.py` | Validation, `{{steps.x.output}}` templates, SQLite | shared |

Tests are in `backend/tests/`. They include property tests (hypothesis) that check the topological order, the levels and the critical-path DP against brute force on random DAGs, and the scheduler's invariants under every policy.
