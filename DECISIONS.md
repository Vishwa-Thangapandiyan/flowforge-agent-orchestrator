# FlowForge — Design Decisions (V1)

Decisions that fill the gaps left open in [FlowForge_V1_Plan.md](FlowForge_V1_Plan.md). Each one has the choice, the reason, and where it lives in the code.

**Hard constraint: zero cost.** No paid API or service anywhere. The LLM provider is NVIDIA NIM's free tier (see D8).

---

## D1. Step durations (the critical-path weights)

**Choice:** a three-level fallback. Use the history from past runs if there is any. If not, use the step's `estimated_ms` from the JSON. If that is missing too, use a default for the step type.

| Step type | Default estimate |
|---|---|
| `llm` | 3000 ms |
| `mcp` | 1000 ms |
| `http` | 300 ms |
| `mock` | its own `duration_ms` |

- **History:** after every run, the measured durations go into SQLite. The estimate is an EWMA (α = 0.3) over past runs, keyed by `(workflow_id, step_id)`. The EWMA weights recent runs more heavily.
- **Output:** every run reports the **predicted** critical path (computed before the run) and the **actual** one (measured afterwards).

**Why:** the DP needs weights before execution starts. The EWMA corrects bad hand estimates over time. The predicted-vs-actual comparison is good material for the write-up.

**Code:** `scheduler/durations.py`, `scheduler/critical_path.py`.

## D2. Passing data between steps

**Choice:** templates in the style of GitHub Actions, placed inside any string in a step's `params`:

```json
"prompt": "Summarize this: {{steps.fetch_stripe.output.body}}"
```

- The path after `output` walks dict keys, or list indices like `items.0.name`.
- **Validation rule:** a step may only reference steps listed in its own `depends_on`. Anything else is a validation error, because a hidden dependency would silently break the ordering.
- A string that is exactly one template, such as `"{{steps.x.output}}"`, is replaced by the raw value (a dict, list or number). Otherwise the value is interpolated into the string with `str()`.
- Templates are resolved at run time, just before the step runs.

**Code:** `templating.py`, and the checks in `schema.py`.

## D3. Caching

Two layers.

1. **Within one run (always on)**
   - The key is `sha256(type + canonical JSON of the resolved params)`. Canonical means the keys are sorted and there is no whitespace.
   - **Single-flight:** if an identical call is already running, the second caller awaits the same `asyncio.Future` instead of making a new request.
2. **Across runs (SQLite), only where it's safe**

| Step type | Cached across runs by default? |
|---|---|
| `llm` | only if `temperature == 0` |
| `http` | only for `GET` |
| `mcp` | no. Tools can have side effects, so a step must opt in with `cache: true` |
| `mock` | no |

- Any step can override the default with `"cache": true` or `"cache": false`.

**Why:** the free tier allows about 40 requests per minute, so every cache hit saves time *and* request budget. The benchmark reports both. The rules stop the cache from serving stale results for non-deterministic or side-effecting calls.

**Code:** `scheduler/cache.py`, `storage.py`.

## D4. What "parallel" means

The accurate wording, for the report and the viva: *FlowForge runs independent, I/O-bound steps **concurrently** on one asyncio event loop.* It is not CPU parallelism. Any future CPU-bound step type must use `loop.run_in_executor` with a process pool.

## D5. Scheduling with limited resources (the main algorithm)

**Choice:** **critical-path list scheduling** (HLFET, "highest level first").

- Each step's **priority** is its **bottom level**: the longest weighted path from that step to the end of the workflow, the step itself included. It is computed with the same DP as the critical path, run in reverse topological order.
- **Two resources** limit how many steps can run:
  - a global limit of `k` steps running at once (`max_concurrency`, default 4), plus optional limits per step type
  - a token-bucket **rate limiter** per provider (NIM: 40 requests/min, see D8)
- When a slot and a token are both free, the ready step with the **highest bottom level** runs next. A heap handles this in `O(log n)`.

**Theory for the viva:**
- Scheduling a DAG on `k` workers to minimise the finish time is NP-hard (P|prec|Cmax).
- Graham (1966): any list schedule has a finish time of at most `(2 − 1/k) · OPT`.
- Critical-path priority is the standard heuristic that does well in practice.
- **Lower bound** used in the benchmark: `max(critical path length, total work / k)`.

**Code:** `scheduler/executor.py`, `scheduler/rate_limit.py`.

## D6. Benchmark design

**Strategies compared** (each one with and without the cache):

| # | Strategy | What it shows |
|---|---|---|
| S1 | Sequential, in topological order | the naive baseline |
| S2 | Level-by-level (BFS layers, wait for the whole layer to finish) | the obvious "parallel" attempt |
| S3 | Greedy, unlimited concurrency | the upper bound on concurrency |
| S4 | `k` slots, FIFO ready queue | limits applied, no priority |
| S5 | `k` slots, critical-path priority | **FlowForge** |

**Metrics:**
- finish time of the whole workflow
- number of API requests and tokens
- cache hit rate
- ratio to the lower bound from D5

**Two tracks:**
1. **Real track:** the example workflows against real NIM, MCP and HTTP. It stays small because of the rate limit: a few runs each, spaced apart.
2. **Simulated track:**
   - 500+ random DAGs generated by `benchmarks/random_dag.py`, varying the number of steps, width and edge density
   - run with `mock` steps that just sleep
   - sleep durations are sampled from the latency distribution measured in the real track
   - results are reported as mean ± 95% CI

**Why:** the real track proves the system works on real calls. The simulated track gives statistically meaningful comparisons at no cost.

## D7. Validation, failures and timeouts

**Validation** (runs before execution; any error rejects the whole workflow):
- the JSON shape (Pydantic)
- duplicate step IDs
- `depends_on` pointing at unknown steps
- a step depending on itself
- templates that reference steps outside `depends_on` (D2)
- **cycles:** Kahn's algorithm detects them; a DFS then reports the actual loop, e.g. `a → b → c → a`

**Failures** (Airflow's `upstream_failed` behaviour):
- A failed step marks every step that depends on it, directly or indirectly, as `skipped`.
- Independent branches keep running.
- The run ends as `failed` if any step failed, and `succeeded` otherwise.

**Retries:**
- `retries` is set per step and defaults to 2.
- Only transient errors are retried: HTTP 429, HTTP 5xx, timeouts and connection errors.
- The wait between attempts is exponential backoff with full jitter, `sleep = random(0, min(cap, base · 2^attempt))`, with base = 1 s and cap = 30 s.
- If the response has a `Retry-After` header, that value is used instead.
- Every retry takes a new rate-limiter token first, so retries cannot cause more 429s.

**Timeouts:**
- `timeout_s` is set per step and enforced with `asyncio.wait_for`.
- Defaults: `llm` 60 s, `mcp` 30 s, `http` 30 s.

**Code:** `schema.py`, `scheduler/graph.py`, `scheduler/executor.py`.

## D8. The LLM provider: NVIDIA NIM (free)

- **Endpoint:** `https://integrate.api.nvidia.com/v1`. It is OpenAI-compatible, so the free `openai` Python package is the client.
- **Key:** `NVIDIA_API_KEY`, from a free NVIDIA developer account at build.nvidia.com. It goes in `.env`, which is gitignored.
- **Default model:** `meta/llama-3.1-8b-instruct`. It is small and fast. Any catalog model can be set per step.
- **Limit:** about 40 requests per minute. NVIDIA doesn't publish a fixed quota per model, so the value can be configured (`NIM_RPM`).
- Tests **never** call the network. They use `mock` steps only.

## D9. Other choices

| Area | Choice |
|---|---|
| Packaging | `uv`, Python ≥ 3.12 |
| Tests | `pytest` and `pytest-asyncio`. `hypothesis` for property tests (e.g. "every topological order respects every edge" on random DAGs) |
| Frontend | one plain HTML page. Live updates over **Server-Sent Events** (`GET /runs/{id}/events`). No React, no build step |
| Storage | SQLite (`flowforge.db`): the run history, the duration history (D1) and the persistent cache (D3) |
| MCP | the official `mcp` Python SDK over stdio, connected to `mcp-server-fetch` (run with `uvx`, free and open source) |
| HTTP | `httpx` (async) |
| Example workflow | `stripe_to_razorpay.json`: fetch the Stripe and Razorpay docs in parallel, summarise each with the LLM, map Stripe endpoints to Razorpay endpoints, then generate migration notes and a risk report. It has parallel branches, a clear critical path and a duplicate fetch for the cache to catch |

## Step JSON schema (reference)

```json
{
  "id": "stripe_to_razorpay",
  "name": "Stripe → Razorpay migration analysis",
  "max_concurrency": 4,
  "steps": [
    {
      "id": "fetch_stripe",
      "type": "http",
      "depends_on": [],
      "params": { "method": "GET", "url": "https://docs.stripe.com/api/charges" },
      "estimated_ms": 400,
      "timeout_s": 30,
      "retries": 2,
      "cache": null
    }
  ]
}
```

`type` is one of `llm | mcp | http | mock`. Every field except `id`, `type` and `params` is optional.
