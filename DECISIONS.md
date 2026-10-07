# FlowForge — Design Decisions

Every design decision, with the choice, the reason, and where it lives in the code. D1–D9 were made for V1 ([FlowForge_V1_Plan.md](FlowForge_V1_Plan.md)) and still hold on `main`. D10–D16 cover the product (connectors, approval gates, MCP, local commands, planning, the frontend, run history and redaction); new decisions take the next free number and are written before the code. A decision is never edited to mean something new: it is superseded by a later entry that says so.

**Hard constraint: zero cost by default.** No paid API or service in the default install, the tests or CI. The default LLM provider is NVIDIA NIM's free tier (see D8).

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

**Why:** the DP needs weights before execution starts. The EWMA corrects bad hand estimates over time. The predicted-vs-actual comparison shows users how accurate the estimates are.

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

The accurate wording, in docs and the UI: *FlowForge runs independent, I/O-bound steps **concurrently** on one asyncio event loop.* It is not CPU parallelism. Any future CPU-bound step type must use `loop.run_in_executor` with a process pool.

## D5. Scheduling with limited resources (the main algorithm)

**Choice:** **critical-path list scheduling** (HLFET, "highest level first").

- Each step's **priority** is its **bottom level**: the longest weighted path from that step to the end of the workflow, the step itself included. It is computed with the same DP as the critical path, run in reverse topological order.
- **Two resources** limit how many steps can run:
  - a global limit of `k` steps running at once (`max_concurrency`, default 4), plus optional limits per step type
  - a token-bucket **rate limiter** per provider (NIM: 40 requests/min, see D8)
- When a slot and a token are both free, the ready step with the **highest bottom level** runs next. A heap handles this in `O(log n)`.

**Theory:**
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
- **cycles:** Kahn's algorithm detects them; following parent links from a leftover step then reports the actual loop, e.g. `a → b → c → a`

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

> Superseded in part by **D10**: NIM is now the *default* LLM connector, not the only provider. Everything below still describes the default.

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
| Example workflow | `stripe_to_razorpay.json`: fetch the Stripe and Razorpay API docs (their `.md` versions over HTTP, plus the Stripe lifecycle page through MCP fetch) in parallel, summarise each with the LLM, map Stripe endpoints to Razorpay endpoints, then generate migration notes and a risk report. It has parallel branches, a clear critical path and a duplicate fetch for the cache to catch |

## D10. Connectors: any LLM, any HTTP API, configured once (Phase 1)

**Supersedes D8** where D8 makes NIM the only LLM provider. NIM stays the **default** provider, with the same free endpoint, key and model.

**Choice:** a **connector** is configuration (who, how to connect, which secret, how it looks). A **Node** is the runtime code that makes one call. Connectors build and configure Node instances. The executor still sees only `node.run(params)`.

- **Model:** `Connector` in `connectors/models.py`, shaped as in CLAUDE.md §7.1 (`id`, `type`, `name`, `role`, `slot`, `style`, `connection`, `secret_ref`, `mode`, `rate_limit_rpm`, `data_sent`, `fallback`). `connection` depends on `type`:
  - `llm`: `provider` (`openai_compatible` | `anthropic`), `base_url`, `model`. `openai_compatible` covers NIM, Gemini's OpenAI endpoint, Ollama, vLLM and OpenRouter.
  - `http`: `base_url`, `auth_header`, `auth_scheme` (`bearer` | `basic` | `raw`).
  - `mcp`: see D12. `local`: see D13.
- **Step → connector:** `Step` gains an optional `connector` (a connector id). If it is missing, the step uses its **type's default connector**, so every workflow written before D10 is still valid and behaves the same. The connector's type must equal the step's type. An unknown connector or a type mismatch rejects the run before it starts.
- **Secrets are references, never values.** `secret_ref` is `env:NAME` (read from the environment when the node first needs it) or `vault:NAME` (reserved for the Phase 3 vault, rejected until then with a clear message). No connector JSON, API response or log holds a key.
- **Rate limits:** each connector with `rate_limit_rpm` owns its **own** token bucket, keyed by its id. The default NIM connector keeps the key `"nim"` and the `NIM_RPM` setting, so existing behaviour and benchmarks are unchanged.
- **Cache (extends D3):** the cache key's namespace is the node's `cache_namespace` instead of the bare step type: `"<type>:<connector id>"`, so two providers given the same prompt never share an answer. Default connectors keep the bare type (`"llm"`, `"http"`, …), so cache rows written before D10 stay valid. The D3 rules on *what* is cacheable are unchanged.
- **Fallback:** `connector.fallback` names another connector of the same type. It is used **only after every retry of a step failed with a transient error or a timeout** (D7). A permanent error (bad request, auth) never falls back, because the request itself is wrong. There is one hop, no chains. The fallback uses its own bucket and its own retries. The run emits a `fallback` event, and the step result records `answered_by`.
- **Usage:** LLM output keeps `{"text", "model", "usage": {"prompt_tokens", "completion_tokens"}}` and adds `usage.credits`, which is `0` until a provider reports credits. FlowForge does not invent prices.
- **Error mapping (unchanged from D7):** 429, 5xx, timeouts and connection errors are transient (honouring `Retry-After`); everything else is permanent. Error messages name the provider, not "NIM".
- **Phase 1 configuration:** connectors live in the SQLite table `connectors`. `nim` (default `llm`) and `fetch` (default `mcp`) are seeded on first start. Further connectors are loaded at start-up from the optional file `FLOWFORGE_HOME/connectors.json` (default `~/.flowforge`), validated by the same models. Write routes and forms arrive in Phase 3. Brands (presets) appear only in `connectors/presets.py`.

**Why:** "any LLM" must not mean "any LLM sharing one rate limit and one cache". Separate buckets and namespaces keep each provider's limits and answers apart, and keeping the old keys for the defaults means nothing that already works changes.

**Code:** `connectors/`, `nodes/llm_node.py`, `nodes/http_node.py`, `scheduler/executor.py` (node lookup, cache namespace, fallback), `scheduler/cache.py`.

## D11. Reserved: approval gates (Phase 4)

Reserved for the gate step described in CLAUDE.md §8. Written before Phase 4's code, together with D14: gates ship in the same phase as the Planner, because a plan can include side effects. D14 fixes the policy of *which* steps are always gated; D11 will define *how* a gate works (step type, slots, events, persistence).

## D12. MCP connectors: any server, discovered tools (Phase 1)

**Choice:**
- **Connection:** `command`, `args`, `env` (plain values) and `env_refs` (env var name → secret ref, see D10). Secret env values are resolved only when the server process is spawned.
- **Discovery:** `list_tools()` on the shared connection returns each tool's `name`, `description` and JSON `input_schema`. It is cached per connection and exposed at `GET /connectors/{id}/tools`.
- **Validation at run time:** before calling, the node checks that `params.tool` exists and that `params.arguments` match its `input_schema` (JSON Schema). A mismatch is a permanent error and the tool is not called.
- **Validation before a run:** `POST /validate` and `POST /runs` try discovery for each MCP connector the workflow uses (5 s timeout). If the server is reachable, a bad tool name or bad literal arguments reject the workflow with the exact reason (422). If it is not reachable, the response carries a warning instead and the run-time check still applies. Arguments containing `{{templates}}` are checked at run time only.
- **Results:** text blocks are joined into `content` as before, and `structured` is unchanged. Non-text blocks go in a `blocks` list, which is **present only when there are any**, so text-only results keep their old shape:
  - image or audio: `{"kind": "image"|"audio", "mime", "data_b64"}` if 64 KB or less, otherwise the bytes are written to `FLOWFORGE_HOME/artifacts/<run_id>/<sha256>.<ext>` and the block holds `"path"` instead
  - resource link: `{"kind": "resource", "uri"}`
  - embedded resource: its text inline, or a blob handled like an image
- Large payloads are never put in the run JSON, events or cache.

**Why:** "any MCP server" is only useful if FlowForge can tell the user what a server offers and catch a wrong call before it runs, and if images or audio don't swell the run history.

**Code:** `nodes/mcp_node.py`, `main.py`.

## D13. Local command step (Phase 1)

New step type `local`: runs a command configured on a connector, with arguments from the step. It is how local scripts and tools plug in.

**Choice (safety rules, all enforced in code and tested):**
- The connector fixes the program (`command`, an argv list) and the folder (`cwd`). The step supplies `args` (a list of strings, appended), and optionally `stdin`, `subdir` and `ok_exit_codes`.
- **No shell, ever.** The process is started from an argv list. Step values are separate arguments, never pasted into a command string. On Windows, `.bat` and `.cmd` programs are refused, because Windows runs them through `cmd.exe`, which would bring shell parsing back.
- **Folder restriction:** `subdir`, after resolving `..` and symlinks, must stay inside the connector's `cwd`.
- **Explicit environment:** the process gets the connector's `env`, its resolved `env_refs` and a minimal allowlist the OS needs to start a program (`PATH`; on Windows also `SYSTEMROOT`, `TEMP`, `TMP`). Nothing else is inherited from FlowForge's environment.
- **Timeout:** the step's `timeout_s` (D7) applies. On timeout or cancellation the process is killed and reaped.
- **Output:** `{"kind": "text", "stdout", "stderr", "exit_code"}`, each stream capped at the connector's `max_output_bytes` (default 1 MB). An exit code outside `ok_exit_codes` (default `[0]`) is a permanent error carrying the end of stderr.
- **Cache:** not cached across runs by default (it may have side effects), like `mcp` in D3.
- **Defaults (extends D1 and D7):** estimate 1000 ms, timeout 60 s.

**Why:** local tools are where the most damage is possible, so the rules close off shell injection, path escape and environment leaks by construction rather than by care.

**Code:** `nodes/local_node.py`, `schema.py`, `scheduler/durations.py`.

## D14. Plan from connectors: the user never edits a graph (Phase 4)

**Choice:** the user connects apps; a **Planner LLM** proposes the tasks and their order from what is connected; FlowForge compiles that plan into a DAG, validates it, and shows the user a plain list to confirm once. The scheduler then runs it. **The LLM decides WHAT. The scheduler decides WHEN. The LLM proposes; the user approves.** The DAG stays under the hood.

**Input: the fact sheet.** It is built by plain code with no LLM, then passed through `redact` (CLAUDE.md §6.4) before any prompt:
- each connector's `describe()` output: id, type and role, plus MCP tools with JSON input schemas, HTTP endpoints from OpenAPI/docs when given, LLM provider and model, and a local command's accepted arguments. Secret *references* only, never values;
- for a linked repo: the file tree, dependency files, route and webhook handlers with `file:line`, and env var *names* (never values);
- the user's goal, in plain language.

The fact sheet is hashed, so every plan version records exactly which facts it was made from.

**Output: a typed plan** (Pydantic, `extra="forbid"`; anything else is rejected):

```json
{
  "goal": "verify captured payments and notify the shop",
  "tasks": [
    {
      "id": "fetch_order",
      "title": "Fetch the order for the payment",
      "type": "http",
      "connector": "razorpay",
      "params": { "method": "GET", "url": "orders/{{steps.webhook.output.order_id}}" },
      "depends_on": ["webhook"],
      "evidence": [{ "kind": "route", "ref": "GET /orders/{id}" }],
      "why": "the risk check needs the order amount"
    }
  ]
}
```

`evidence.kind` is `tool` (an MCP tool name), `endpoint` (an HTTP route from `describe()`), `route` or `file` (a `path:line` from the repo facts). The plan carries no code, no shell commands and no secrets.

**Evidence rule (anti-hallucination):** every evidence `ref` must match an entry in the fact sheet exactly. A task with no valid evidence is **dropped**, and so is every task that depends on it. The plan review lists what was dropped and why. FlowForge never invents a replacement.

**Validation.** The surviving plan compiles to ordinary workflow JSON and passes the same checks as hand-written workflows:
- schema (`schema.py`) and template references (D2);
- cycles (`graph.py`, D7);
- unknown connector or type mismatch (D10);
- unknown MCP tool or arguments that fail its schema (D12).

On failure, FlowForge makes **at most 2 automatic repair calls**, each including the exact validation errors. After that the user sees the error; there is no silent failure and no partial run.

Validation catches structural errors, not wrong ideas. That is why the confirmation and the gates below are not optional.

**Plan review and confirmation.** The user sees **"Here's what will happen"**, a list rather than a graph:
- the steps in order, with the ones that run together grouped;
- the estimated time (critical path, D1/D5);
- each step's connector and the secret *names* it touches;
- which steps need approval;
- what was dropped and why.

One confirmation ("Looks good, run it") starts the run.

**Gating policy (always, no exceptions).** A gate (D11) precedes every payment step, every code change and every side-effecting step. *Code* decides what counts as side-effecting, never the Planner:
- non-GET HTTP;
- connectors in a payments slot or with a `mode`;
- MCP tools not annotated read-only;
- every `local` step;
- anything that writes to a repo.

The Planner can add gates but never remove them. No setting turns this policy off.

**Plan versioning.** A confirmed plan is stored as a version: `plan_versions(plan_id, version, fact_sheet_hash, planner_connector, plan_json, workflow_json, dropped_json, created_by, confirmed_at)`. Re-planning, or a changed fact sheet or connector set, creates version N+1, which must be confirmed again. A run always references the exact version it ran, and older versions stay runnable for rollback.

**Planner calls** use any LLM connector, chosen in settings as the "Planner model". They run at temperature 0, are cached like any LLM call (D3), and count toward money and time.

**Untrusted input.** Repo text, API docs and tool descriptions are data, not instructions. Text inside them that tries to steer the Planner must not change the plan's gating. A plan that adds a connector, widens access or turns on a side effect is flagged in the review. Planner output is parsed and validated, never executed, `eval`'d or shelled out; only the scheduler runs steps, and only after confirmation.

**Advanced path.** Hand-written workflow JSON, `POST /validate` and `POST /runs` keep working unchanged for developers and CI. A graph view may exist under Advanced only.

**Why the user never edits a graph:**
- The graph is how the scheduler sees the work, not how people think about it. People think "when a payment is captured, check the risk, then mark the order verified".
- Hand-editing edges is where structural mistakes come from (missing dependencies, cycles, a step wired to the wrong app). Code is better at those checks, and a person is better at judging whether the list of steps makes sense.
- Moving the person's job from drawing to reviewing makes the review the one moment where human judgement matters most. The gates then cover the cases where being wrong costs money or code.

**Supersedes:** the earlier Phase 4b idea (suggested tasks with Accept/Edit/Dismiss, drag-to-rewire, graph before/after previews). It was never implemented and had no D-number.

**Code:** `planner/` (Phase 4), plus the existing checks in `schema.py`, `scheduler/graph.py`, `scheduler/executor.check_nodes` and `nodes/mcp_node.check_call`. Connectors gain `describe()`.

## D15. Frontend stack (Phase 2)

**Choice:** Vite + React + TypeScript in `frontend/`, with `react-router-dom` for pages.
- **Styling:** plain CSS using the design tokens copied from `docs/design/system-map.html`, light and dark. No UI kit and no animation library: motion is CSS plus the Web Animations API, and all of it switches off under `prefers-reduced-motion`.
- **Fonts:** Bricolage Grotesque, IBM Plex Sans and IBM Plex Mono, self-hosted through `@fontsource`. Nothing is fetched from a font CDN at runtime.
- **Brand marks:** preset brands use the CC0 SVGs from the `simple-icons` package, as nominative use to identify an integration. Anything not in the package, plus custom apps, gets a monogram tile or the user's uploaded image.
- **Tests:** Vitest + Testing Library on jsdom, plus `tsc` type checks.
- **Dev:** `npm run dev` (in `frontend/`) runs the API in example mode and Vite together; Vite proxies API calls.
- **Production:** `npm run build` writes `frontend/dist`, and `uv run flowforge` serves it from FastAPI and opens the browser.
- **Old page:** the V1 `frontend/index.html` stays at `/classic` until the new UI reaches parity.
- **Routing:** page routes and API paths overlap (`/runs/:id`, `/connectors/:id`). A `GET` whose `Accept` header prefers `text/html` gets the app; anything else gets JSON, so curl, CI and the existing API keep working unchanged.

**Why:** a component model suits pages that share live state (SSE runs, connector health). TypeScript catches API-shape drift. Keeping plain CSS and a few dependencies keeps the zero-cost, local-first install small. Backend-only contributors can still use `uv run uvicorn` without Node.

**Code:** `frontend/`, `backend/flowforge/spa.py`, `backend/flowforge/cli.py`.

## D16. Run history, redaction before storage, example mode, editable connectors (Phase 2)

**Choice:**
- **Runs persist.** A run row is written when the run starts (`running`) and updated when it ends (`succeeded` | `failed` | `stopped`). Every event goes to a `run_events` table as it is emitted. Totals (calls, cache hits, tokens, credits, step time) are stored per run, so history and savings need no re-parsing. Runs still marked `running` when the server starts become `interrupted`. The in-memory buffer remains only for the live SSE stream.
- **Redact before storing (pulled forward from CLAUDE.md §6.5).** `security/logfilter.py` masks two things as `[REDACTED]`:
  - strings matching known key shapes (`sk_live_`/`sk_test_`, `rzp_live_`/`rzp_test_`, `AIza…`, `nvapi-…`, `sk-ant-…`, JWT-shaped tokens, PEM blocks);
  - the current values of every env var a connector's `secret_ref`/`env_refs` names, plus `NVIDIA_API_KEY`, including their Basic-auth base64 form. Values shorter than 8 characters are never masked, to avoid mangling ordinary text.

  It runs on every event before it is stored or streamed, on run results before storage and API responses, and as a `logging.Filter` on the root and uvicorn loggers. The promise stays honest: it *catches known key formats and configured keys*, not everything. Phase 3 replaces it with the full vault and redact/verify/scan/restore.
- **Stop, not pause.** `POST /runs/{id}/stop` cancels the run; the executor cancels its running steps. Pausing would need a scheduler change, so it is out of scope.
- **Events carry what a live view needs (additive; scheduling unchanged).**
  - The `run started` event also carries `predicted_critical_path_ms` and each step's estimate (`estimates`).
  - A step's `succeeded` event carries its `output`, so the dashboard can show outputs and token counts before the run ends.
  - Each run stores its plan outline: step id, title, type, connector and dependencies, never params.
  - `StepResult.answered_by` is now set on every attempt, so a failure is attributed to the connector that was tried.
- **Editable connectors.** `POST/PUT/DELETE /connectors` save to the registry and rebuild that connector's node and rate-limit bucket in place. Runs already in flight keep the node they started with.
  - Keys are entered as an env var *name* only (`secret_ref: env:NAME`). Responses say `set` or `missing`, never the value.
  - Connectors defined in `FLOWFORGE_HOME/connectors.json` are upserted at every start-up (D10), so they are marked `managed_by: "file"` and are read-only through the API and UI; that way a UI edit can't be silently overwritten.
  - `nim` and `fetch` cannot be deleted.
- **Logos.** Uploaded logos follow CLAUDE.md §6.5: PNG/JPEG/WebP only, at most 1 MB, checked by magic bytes, stored at `FLOWFORGE_HOME/logos/<id>.<ext>` and served with a fixed `Content-Type` and `nosniff`.
- **Example mode.** `flowforge --example` (or `FLOWFORGE_EXAMPLE=1`) uses its own database, `FLOWFORGE_HOME/example.db`, so real history is never mixed with demo data. It seeds example connectors with no keys, and offline fake nodes stand in for them. The seeded runs and any demo run started from the UI go through the real executor, so events, timings, history and savings are genuine; the UI labels everything "Example data".

**Why:** a dashboard that forgets runs on restart can't show history or savings. Storing only redacted data means a leak in the UI or a copied database file doesn't leak keys. Example mode lets someone see the whole product without signing up anywhere.

**Code:** `storage.py`, `security/logfilter.py`, `api/`, `example_data.py`, `main.py`.

---

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

`type` is one of `llm | mcp | http | local | mock` (`local` since D13). Every field except `id`, `type` and `params` is optional, including `connector` (D10).
