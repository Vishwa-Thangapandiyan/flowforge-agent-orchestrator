# FlowForge — V1 Plan, Stack & Scaffolding (DAA course project)

> **This plan is complete and frozen.** V1 is the DAA course project. Its code is preserved unchanged on the `DAA` branch, which nobody commits to or merges into. `main` has moved on to the product: the scheduler layer for agent workflows plus a dashboard. The roadmap for that (Phases 1–6) and the rules for working on it are in [CLAUDE.md](CLAUDE.md). See [After V1](#after-v1) at the end for how this plan feeds into it.

Goal for V1: a working, single-machine version that proves the core algorithms and calls real tools (an LLM through NVIDIA NIM, and MCP). No distributed systems yet. Target: about 1 month, 3-person team. **Zero cost: nothing paid.**

Design decisions for every open question are in [DECISIONS.md](DECISIONS.md) (referred to as D1–D9 below). D1–D9 stay in force on `main`. New decisions continue from D10 and never silently change these.

**Status (7 Oct 2026):** all V1 code in the build order below is implemented, tested and benchmarked on the simulated track ([benchmarks/RESULTS.md](benchmarks/RESULTS.md): on 200 random DAGs with `k = 4`, critical-path priority gives an 8.3% ± 1.1% lower makespan than FIFO and is effectively at the lower bound). Course deliverables still open: run the real-track benchmark with a NIM key, record the demo video, and write the report. These are done against the `DAA` branch, not `main`.

---

## What V1 Must Prove

- A workflow (steps + dependencies) is scheduled correctly: a valid order, with independent steps running concurrently.
- Under limited resources (`k` slots + a rate limit), critical-path priority beats naive strategies (D5).
- The bottleneck chain of any workflow is found automatically, both predicted and actual (D1).
- Duplicate calls (same tool, same resolved input) are made only once (D3).
- At least one real integration (an LLM through NVIDIA NIM, and/or an MCP tool) actually runs. Not mocked.
- A clear benchmark with real numbers: the 5 strategies compared on real workflows plus 500+ random DAGs (D6).

---

## Stack

Kept deliberately simple. The algorithms are the point, not the tech. Everything is free and open source.

| Layer | Choice | Why |
|---|---|---|
| Backend | Python ≥ 3.12 + FastAPI, managed with `uv` | One language throughout; async support built in |
| Concurrent execution | Python `asyncio` | Concurrent I/O-bound steps, no queue or infra needed yet (D4) |
| Workflow definition | Plain JSON (steps + `depends_on` + `{{steps.x.output}}` templates) | Skip a drag-and-drop builder. That's UI polish, not algorithm work (D2) |
| LLM integration | NVIDIA NIM free tier through the `openai` package (OpenAI-compatible) | Free. About 40 requests/min, which makes rate-limited scheduling a real problem (D8) |
| MCP integration | Official `mcp` Python SDK + `mcp-server-fetch` | A real MCP tool at no cost |
| HTTP integration | `httpx` | Async HTTP client |
| Frontend | One plain HTML page + Server-Sent Events | Paste JSON, hit run, watch the steps light up live. No build step |
| Storage | SQLite | Run history, duration history (D1), persistent cache (D3) |
| Tests | `pytest`, `pytest-asyncio`, `hypothesis` | Property tests on random DAGs. Tests never hit the network |

---

## Scaffolding

```
Project/
├── DECISIONS.md
├── pyproject.toml
├── .env.example                  # NVIDIA_API_KEY, NIM_RPM
├── backend/
│   ├── flowforge/
│   │   ├── main.py               # FastAPI app: POST /runs, GET /runs/{id}, GET /runs/{id}/events (SSE)
│   │   ├── schema.py             # Pydantic workflow models + validation (D7)
│   │   ├── templating.py         # {{steps.x.output.path}} resolution (D2)
│   │   ├── storage.py            # SQLite: runs, durations, persistent cache
│   │   ├── scheduler/
│   │   │   ├── graph.py          # DAG build, topological sort, cycle detection + reporting
│   │   │   ├── critical_path.py  # DP: critical path + bottom levels (priorities)
│   │   │   ├── durations.py      # estimate fallback chain + EWMA history (D1)
│   │   │   ├── executor.py       # asyncio list scheduler: k slots, priority heap, retries, timeouts, skip-on-failure
│   │   │   ├── rate_limit.py     # async token bucket (D5/D8)
│   │   │   └── cache.py          # single-flight in-run memo + persistent cache (D3)
│   │   └── nodes/
│   │       ├── base.py           # Node interface + errors (transient vs permanent)
│   │       ├── llm_node.py       # NVIDIA NIM chat completion
│   │       ├── mcp_node.py       # MCP tool call
│   │       ├── http_node.py      # plain HTTP call
│   │       └── mock_node.py      # sleeps for duration_ms; for tests + simulated benchmark
│   ├── workflows/
│   │   ├── stripe_to_razorpay.json
│   │   └── diamond_mock.json
│   └── tests/
├── frontend/
│   └── index.html
└── benchmarks/
    ├── random_dag.py             # random DAG generator
    └── run_benchmark.py          # strategies S1–S5, real + simulated tracks
```

---

## Build Order (don't skip ahead)

1. **Workflow JSON shape + `schema.py` validation.**
2. **`graph.py`:** build the DAG, topological sort (Kahn's), cycle detection that reports the actual loop. Test on small examples you can check by hand, then use property tests.
3. **`executor.py` (basic):** run in a valid order with unlimited concurrency, using `mock` steps only.
4. **Wire in one real step type:** `llm_node.py` against NIM, so early on you're proving it on something real.
5. **`critical_path.py` + `durations.py`:** the DP for the critical path and the bottom-level priorities.
6. **`executor.py` (full):** `k` slots + priority heap + `rate_limit.py` + retries/timeouts/skip-on-failure.
7. **`cache.py`:** single-flight memo, then the persistent layer.
8. **`mcp_node.py`, `http_node.py`**, then the frontend.
9. **`run_benchmark.py`:** S1–S5 on the real + simulated tracks.

---

## Rough Weekly Split (1 month)

- **Week 1:** `graph.py` + tests, basic executor on mock steps, NIM key set up and `llm_node.py` working.
- **Week 2:** `critical_path.py`, `durations.py`, full executor (priority + rate limit + failures), `http_node.py`.
- **Week 3:** `cache.py`, `mcp_node.py`, frontend (SSE status view), `random_dag.py`.
- **Week 4:** benchmarks (both tracks), polish, demo video, write-up.

---

## Team Split (suggested, 3 people)

- **Person A:** `graph.py` + `critical_path.py` + `durations.py`: the core DAG algorithms, correctness and property tests, and the Graham bound argument for the viva.
- **Person B:** `executor.py` + `rate_limit.py` + `cache.py`: the scheduling engine, resource limits, memoization.
- **Person C:** `nodes/` (NIM/MCP/HTTP) + frontend + `benchmarks/`.

All three co-own the final write-up and can each defend their own piece in a viva.

---

## After V1

V1 is the foundation of the product, not something to replace. On `main` the rule is **extend it, don't rewrite it** (CLAUDE.md §4): the scheduler, the five policies, the caches and the benchmarks keep working unchanged through every later phase.

### Known limits of V1 (these are Phase 1's job)

| V1 limit | Fixed in |
|---|---|
| `LLMNode` is hard-wired to NIM (`rate_limit_key = "nim"`, one base URL and model from env, errors say "NIM") | Phase 1: provider-agnostic LLM connectors (OpenAI-compatible endpoints such as NIM, Gemini, Ollama, plus Anthropic), each with its own rate-limit bucket |
| `MCPNode` has no tool discovery, no per-server env secrets, and only handles text results | Phase 1: any MCP server, discovered tools with schema checks, image/audio/resource results |
| The four step types are hard-coded in `main.py`'s lifespan | Phase 1: connector registry in SQLite, plus a new `local` command step type |
| Step outputs have no `kind` hint for viewers | Phase 1 onward (CLAUDE.md §7.4) |
| Runs are kept in memory only | Phase 2: SQLite-backed run history |
| One plain HTML status page | Phase 2: dashboard built to the design in `docs/design/system-map.html` |
| No secrets handling beyond `.env` | Phase 3: vault, redaction, guards (CLAUDE.md §6) |
| No linter, no CI | Phase 1: `ruff` + GitHub Actions, offline |

### How V1 maps onto the roadmap

| V1 piece | Where it goes next |
|---|---|
| Scheduler core (`graph`, `critical_path`, `durations`, `executor`, `rate_limit`, `cache`) | Unchanged. Connectors build `Node` instances; the executor keeps calling `node.run(params)` |
| `nodes/` | Configured by connectors (Phase 1), placed on workers via `RemoteNode` (Phase 5) |
| `frontend/index.html` | Kept until the Phase 2 dashboard reaches parity, then removed in its own commit |
| `benchmarks/` | Must keep running unchanged; Phase 5 adds a worker-dropout track |
| Two-machine idea | [FlowForge_Server_Orchestrator_Plan.md](FlowForge_Server_Orchestrator_Plan.md) (Phase 5, after Phase 3) |
