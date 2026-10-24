# FlowForge — Design Decisions

Every design decision, with the choice, the reason, and where it lives in the code. D1–D9 were made for V1 ([FlowForge_V1_Plan.md](FlowForge_V1_Plan.md)) and still hold on `main`. D10–D18 cover the product (connectors, approval gates, MCP, local commands, planning, the frontend, run history and redaction, the flow map). D19–D20 set the current direction: repo → dependency map → health, security and tests, with a scan that sends nothing to an LLM. D21 is the scanner contract and D22 the rules learned from the first real scans; new decisions take the next free number and are written before the code. A decision is never edited to mean something new: it is superseded by a later entry that says so.

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

> Partly superseded by **D17**. The home page is now a Planner-drawn flow map the user can edit through overrides. The engine is hidden, and the View 7 list is gone. The fact sheet, evidence rule, validation, gating policy, versioning and untrusted-input rules below still hold.

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
- **Fonts:** Bricolage Grotesque, IBM Plex Sans and IBM Plex Mono, self-hosted through `@fontsource`. Nothing is fetched from a font CDN at runtime. *(Superseded by D18: Geist and Geist Mono.)*
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

## D17. The flow map: a Planner-drawn map of the app's AI flow (Phase 3)

**Supersedes parts of D14:**
- "the user never edits a graph";
- "a graph view may exist under Advanced only";
- the View 7 plan-review list;
- "the Planner model is chosen in settings".

Everything else in D14 still holds:
- the fact sheet, and redaction before any prompt;
- the evidence rule;
- validation and the repair limit;
- the gating policy;
- versioning;
- untrusted input.

**What FlowForge is:** an LLMOps tool for apps that already use AI. It is not an app builder.

**Choice:**
- **The home page is the flow map.** The Planner reads the repo and runs the app in test mode. It then draws how the app's LLM, MCP and API calls fit together. Block kinds:
  - `start`, `end`;
  - app calls (`llm`, `api`, `mcp`, `local`) and plain `code`;
  - `decision`, `fork`, `join`, `gate`.

  Line kinds: `flow`, `branch` (with `when`), `fallback`, `retry`, `unconfirmed`. The user can pan, zoom and drag. Positions are saved.
- **The engine is hidden.** The UI says "the Planner". It never names the model behind it, and the user cannot pick it. A user-selectable engine may come later as its own decision.
- **Only apps the code calls go on the map.** A connected app that no code calls stays in the catalog as "connected, not in your code".
- **Evidence or nothing.** Every block carries evidence: a `file:line`, a traced call, or a policy rule. A block with only a hint (for example an env var *name*) is drawn as `unconfirmed` and never runs. A task whose evidence is not in the fact sheet is dropped (D14).
- **Gates are added by code.** Validation puts a gate (`added_by: "policy"`) before every side-effecting block, using the D14 list:
  - non-GET HTTP;
  - payment connectors;
  - MCP tools not marked read-only;
  - `local`;
  - code writes.

  Gates the Planner adds are kept, and no edit can hide or remove a gate.

  **This supersedes one item of D14's list.** "Connectors in a payments slot or with a mode" becomes "calls to them that move money". A GET to a payment API only reads (for example fetching an order), so it isn't gated; every non-GET call to it is, by the non-GET rule. An HTTP call with no method given counts as a write. Unconfirmed blocks never run, so their gate is inserted the moment the user confirms them.
- **Edits are overrides.** The user can swap a block's connector, rename, hide, confirm an unconfirmed block, add a step and wire it after another. Each edit is stored as an override on top of the Planner's version, never instead of it. "Planner's map / With my edits" switches between them. **Map edits never change the user's code.** Writing code for a new connector (a "coding connector") is later work, after the Phase 6 swap flow: it needs a new branch, tests and a gate.
- **Re-check makes a new version, never an overwrite.** It produces pending version N+1 and a diff: added, changed, removed, and conflicts where a change touches a block the user edited. The user picks what to take. Accepting makes N+1 current; older versions stay listed.
- **Test run (V1) replays a recorded trace.** The Planner's output includes the trace of one test order: the path taken, timings, fallback, retries, cache hits and gate stops. The map replays it. A real scheduled run of the flow needs conditional branches and gates in the executor (D11) and is later work.
- **V1 Planner.** A `Planner` interface with one implementation, the example-mode fixture. Real repo analysis comes after the security phase. Outside example mode the map shows an empty state saying so.

**Roadmap renumbered:**
- Phase 3 is now this flow map;
- the security phase (vault, redact/verify/scan/restore) is Phase 4;
- the real Planner with approval gates is Phase 5;
- swap (and later the coding connector) is Phase 6;
- server and workers is Phase 7;
- the visual builder is Phase 8.

D10–D16 were written before the renumbering, so their phase numbers are the old ones: their "Phase 3" means today's Phase 4, their "Phase 4" means Phase 5, and so on.

**Why:** the map shows how the app works, which is what an LLMOps tool is for. Users read the map; they don't draw it. Keeping edits as overrides, and re-checks as diffs, means the Planner's picture and the user's choices never overwrite each other. Code-decided gates keep the Planner from turning off a safeguard.

**Code:** `flowmap/` (models, validation, fixture planner, diff, service), `api/flowmap.py`, `storage.py` (`flow_versions`, `flow_overrides`, `flow_positions`), `frontend/src/flowmap/`.

## D18. Frontend additions for the flow map (Phase 3)

**Supersedes the fonts bullet of D15.** The rest of D15 stands.

**Choice:**
- **Fonts:** Geist (text and headings) and Geist Mono (files, ids, numbers), self-hosted through `@fontsource-variable/geist` and `@fontsource-variable/geist-mono` (OFL). Nothing is fetched from a font CDN.
- **Canvas:** `@xyflow/react` (MIT) for pan, zoom, drag, the minimap and keyboard support. Blocks and lines are our own components drawn with the design tokens.
- **Auto-layout:** `@dagrejs/dagre` (MIT), left to right. It is used for the first layout and for "Re-tidy". elkjs was not chosen: it is EPL/GPL and much larger.
- **Design source:** the approved artboards in `docs/design/flow-map-artboards/`. The colour meanings stay as they were: teal done, blue running, amber waiting for you, coral failed or fallback, violet the Planner and AI.

**Why:** a pannable, draggable canvas with a minimap and keyboard support is a lot to build by hand. React Flow is the standard MIT library for it, and dagre handles left-to-right layered layouts at this size.

**Code:** `frontend/package.json`, `frontend/src/styles/tokens.css`, `frontend/src/flowmap/`.

## D19. Product direction: repo → dependency map → health, security and tests (2026-10-20)

**Supersedes:**
- the pitch "the scheduler layer for agent workflows" (CLAUDE.md §1 before 2026-10-20, and the README);
- D14's core flow (connect apps → the Planner proposes a plan → confirm → the scheduler runs it). D14's evidence rule and untrusted-input rules carry over to the scan;
- D17's V1 source of the map ("the Planner reads the repo and runs the app in test mode"). D17's map UI, overrides, re-check diff and versions stay;
- D17's roadmap numbering. The new roadmap is in CLAUDE.md §5.

**Choice:**
- **What FlowForge is.** The user points it at a repo. It finds every dependency the code uses and draws them as a map. It checks each one's health and security on demand, runs tests against them and shows the results.
  - A **dependency** is an LLM, an MCP server, an HTTP API or a local command the code calls.
  - Libraries that are not services (for example `intl`) are not dependencies here.
- **Input.** A local folder first: `flowforge scan <path>`, or the dashboard. A public GitHub URL comes later; it is cloned into `FLOWFORGE_HOME` and then scanned the same way.
- **The map.**
  - V1 draws the dependency map: the repo and the dependencies it uses, each with `file:line` evidence.
  - The order of calls is added later, from tracing or from the optional LLM (D20).
  - The existing canvas, saved positions, overrides and re-scan → diff → versions (D17) are reused. Overrides let the user add, correct or hide a dependency.
- **Detection doesn't depend on the catalog.** Any URL host, SDK import, MCP config entry or env var name is detected.
  - The catalog adds only a logo and a better health check for apps it knows.
  - An unknown dependency gets the generic checks for its kind.
- **Health checks** run on demand ("Check now"); an optional timer comes later. Generic checks per kind:
  - MCP: it starts, it lists its tools, how fast;
  - HTTP API: reachable, latency, https, certificate expiry;
  - LLM: reachable, model present;
  - local: the program and its folder exist.

  Results are stored per dependency over time. The scheduler runs the checks concurrently under each dependency's rate limit; it is now an internal engine, not the pitch.
- **Security findings:**
  - hard-coded keys, found with the CLAUDE.md §6.4 finders;
  - plain `http://` APIs;
  - risky MCP configs, such as broad filesystem access or unpinned `npx` packages;
  - later, SDK versions with known vulnerabilities.

  A finding names the file, the line and the kind of key. The key's value is never stored, shown or sent anywhere.
- **Pages:** Map (home), Dependencies (the catalog), Checks (replaces Runs: health and test results), Security (findings). Approvals is hidden until V2.
- **V2 (later).** The user adds a dependency on the map. A local coding agent then writes the code on a new branch: Claude Code, Codex or Antigravity, whichever is installed, on the user's own subscription.
  - Keys are moved out of the code first; the "key isolation" auto-fix, which moves a hard-coded key into `.env`, is part of V2.
  - Tests run, and nothing merges without the user's approval.
  - D11 gates, the vault and redact → verify → scan → restore (CLAUDE.md §6.2–6.4) belong to V2.
- **Kept unchanged:**
  - the scheduler, its five policies, caches and benchmarks (D1–D9);
  - connectors (D10, D12, D13);
  - stored runs and redaction (D16);
  - the frontend stack (D15, D18).

  Workflow JSON and `POST /runs` stay as the Advanced path.

**Why:** this is Vishwa's statement of the product (2026-10-20). Developers shipping apps that use LLMs and MCP servers can't see at a glance what their app depends on, whether those services are up, or where the keys sit. Existing tools each cover a piece:
- package scanners look at libraries;
- LLM tracing needs code changes in the app;
- service maps are enterprise products that need instrumentation.

None offers a free, local repo → map → checks loop that needs no change to the app.

**Code:** `scan/` (new, Phase 4), `flowmap/`, `api/`, `frontend/src/`.

## D20. The scan uses no LLM; FlowForge's own LLM is optional and sees only masked findings (2026-10-20)

**Supersedes:**
- D17's "the engine is hidden … the user cannot pick it";
- D14's Planner call as a default step.

**Choice:**
- **The scan is plain code.** It finds dependencies, evidence and security findings with parsers and patterns only.
  - It sends no file, snippet, key or env value from the scanned repo to any LLM or other network service.
  - Health checks call the dependencies themselves, because that is their job. They send no repo content.
- **FlowForge's own LLM is optional, off by default, and the user's choice.**
  - It may later do what plain code can't, such as inferring the order of calls.
  - When it is on, the UI names the model and the user picks it. A local model (Ollama) is suggested first.
  - It receives only the scan's findings, passed through the redactor: dependency names and kinds, `file:line`, and env var *names*. It never receives file contents.
  - With it off, the map, checks and security findings all still work; only those extras are lost.
- **Keys.** The CLAUDE.md §6.1 promise holds for every LLM, FlowForge's own included.
- **Tests.** A fixture repo with fake keys is scanned with the network blocked. The test asserts that no outgoing call is made, and that no stored row, API response or log contains a fake key.

**Why:** the user's code and keys are private, and an LLMOps tool that leaked them to its own model would defeat its purpose. Doing the scan in plain code also makes it free, fast, repeatable and backed by evidence.

**Code:** `scan/`, `security/`.

## D21. The scanner contract: what a dependency is, its evidence, the output, and how it becomes the map (Phase 4)

**Supersedes, for dependency maps only:**
- D17's "gates are added by code" before side-effecting blocks;
- D17's rule that every call block names a connected app.

Both still apply to flow maps (the Baby-care fixture now, flow order in Phase 8).

**What the scanner reads.** Read-only: it never runs, imports or installs anything from the repo, and makes no network call (D20).
- **Which files:** in a git repo, the files git tracks or doesn't ignore (`git ls-files`, run locally). Otherwise a walk that skips `.git`, `node_modules`, `.venv`/`venv`, `build`, `dist`, `.dart_tool`, `__pycache__` and `vendor`.
  - Symlinks are not followed out of the root.
  - Binary files and files over 1 MB are skipped.
  - Test folders (`tests/`, `test/`, `__tests__/`) are skipped, because their URLs are fixtures.
  - Docs (`*.md`, `*.txt`) are skipped, because their links are not calls.
- **How:** Python through the stdlib `ast`. JS/TS and Dart through patterns. JSON, TOML and YAML config through their parsers or patterns.

**What counts as a dependency.** One entry per service:

| Kind | Found from | One entry per |
|---|---|---|
| `llm` | an LLM SDK import (OpenAI, Anthropic, Google GenAI, Mistral, Cohere, Groq, Ollama, LiteLLM, LangChain providers; JS/Dart equivalents), resolved to a provider by its base URL or model names (`localhost:11434` → Ollama, `integrate.api.nvidia.com` → NIM, `generativelanguage.googleapis.com` → Gemini, no base URL → the SDK's own provider) | provider |
| `api` | a URL literal (or an f-string / template / `Uri.parse` whose text *starts with* `http://` or `https://`), or an SDK that stands for a hosted service (`supabase_flutter`, `stripe`, `razorpay`, `firebase_*` …) | host |
| `mcp` | MCP config files (`.mcp.json`, `mcp.json`, `.vscode/mcp.json`, `.cursor/mcp.json`, `claude_desktop_config.json`); `StdioServerParameters(...)` or a JS `StdioClientTransport({...})` with literal command and args | server name |
| `local` | `subprocess.*`, `os.system`, `asyncio.create_subprocess_exec`; Dart `Process.run`; JS `child_process` | program (the script, when it is run by an interpreter) |

The table that maps SDK packages to services lives with the catalog in `connectors/presets.py`, the only place brands are named (D10).

**Not dependencies:**
- the client libraries themselves (`httpx`, `openai`, `mcp`);
- URLs that only appear *inside* a longer string, such as a User-Agent;
- localhost and private addresses, unless the LLM rule claims them (Ollama);
- `example.com`/`.org`/`.net`;
- XML and JSON-schema namespace URLs;
- the commands that start MCP servers (`npx`, `uvx`, `python`).

**Confirmed or unconfirmed (D17's rule, kept).** Unconfirmed entries are drawn dashed. The user can confirm or hide them (an override), and they are never checked until confirmed. An entry is *confirmed* when one of these holds:
- its SDK is imported and used;
- its host matches a catalog app;
- the URL is used in a call the scanner recognises: the first argument or `url=` of an HTTP client call, a `url` key in a dict, or a `Uri.parse` / `fetch` argument, directly or through a module-level constant;
- the URL has an API shape: the host starts with `api.`, or the path has `/api/` or `/v<n>/`;
- it comes from an MCP config or a subprocess call.

Anything else is unconfirmed. Examples: a `www.` page link, or an env var name that hints at a service nobody imports.

**MCP servers your coding tools use.** `.mcp.json` and the other config files often set up the developer's agent (Claude Code, Cursor), not the app.
- If code in the repo names the config file, or a server in it, its servers are the app's dependencies.
- Otherwise they go in a separate group, "Your coding tools". They are still mapped and checked.

**Merging.** One entry per id:
- `llm-<provider>`;
- `api-<host with dots as dashes>`;
- `mcp-<server>`;
- `local-<program>`.

Every place that found the same entry adds its evidence to that one entry. A host only ever reached through an MCP server (a URL passed to an MCP `fetch` call) records `via: "mcp-<server>"`. Hosts of the same site (`thumb.` and `commons.wikimedia.org`) stay separate entries, and the map groups them by site. The ids are stable, so re-scans diff by id and saved positions survive.

**Evidence.** Each entry carries one or more `Evidence(type="code", ref="path:line")`, plus:
- a short excerpt (at most 5 lines), **passed through the redactor before it is stored**;
- the env var *names* on the same statement.

The scanner keeps only a URL's scheme, host and path. Query strings are dropped, because they can hold keys. It never stores any other string literal value, except model names and MCP command arguments, and those are redacted too.

**Output (`ScanResult`, Pydantic, `extra="forbid"`):**

```json
{
  "root": "trip-planner",
  "files_scanned": 14,
  "skipped": {"too_big": 0, "binary": 0, "ignored": 3},
  "languages": {"python": 9, "json": 1},
  "dependencies": [
    {"id": "llm-ollama", "kind": "llm", "name": "Ollama", "catalog": "ollama",
     "target": "localhost:11434", "model": "llama3.1:8b",
     "status": "confirmed", "scope": "app", "via": null,
     "evidence": [{"type": "code", "ref": "services/llm.py:5", "text": "imports the OpenAI SDK"}],
     "env_names": ["OLLAMA_BASE_URL", "PLANNER_MODEL"]}
  ],
  "env_names": [{"name": "CURRENCY_API_URL", "ref": "mcp_servers/currency.py:9"}],
  "findings": []
}
```

`findings` is filled by the security phase (Phase 6). Paths are relative to `root`.

**How it becomes the map.** `ScanPlanner(path)` implements the D17 `Planner` interface and returns the same `Draft`, so versions, re-scan → diff, overrides and saved positions all work unchanged.
- `Flow` gains `kind: "flow" | "dependencies"` (default `"flow"`, so existing maps and tests are unaffected).
- A dependency map has:
  - one `start` block for the app;
  - one `start` block for "Your coding tools" when there are any;
  - one block per dependency (`llm`/`api`/`mcp`/`local`);
  - a line from its root to each dependency, or from the MCP server for `via` entries.
- On a dependency map, validation:
  - does not insert gates;
  - allows a call block with no connector (if one is set, its type must still match);
  - computes no critical path.
- The full `ScanResult` is kept with the version (`Analysis.scan`), so later phases can check each dependency's `target`.
- **One repo per database in V1.**
  - `flowforge scan <path>` prints the `ScanResult` JSON and stores nothing.
  - "Scan a folder" in the dashboard (or `flowforge --repo <path>`) saves the path and draws version 1. Re-scan makes version N+1 with a diff.
  - Pointing at a different folder starts a fresh map, after the user confirms.
- **Example mode shows two maps, switchable (Vishwa, 2026-10-20).**
  - The default is the trip planner's dependency map, scanned live from `examples/trip-planner`.
  - A switch in the map's header shows the Baby-care flow map (gates, test-run replay). It is styled like the existing "Planner's map / With my edits" switch.
  - The flow tables (`flow_versions`, `flow_overrides`, `flow_positions`) gain a `map_id` column (`deps` | `flow`), so the two maps keep separate versions, edits and positions. The flow routes take `?map=`, defaulting to the dependency map.
  - This is also the first step toward more than one repo per database (later).

**Tests (offline):**
- Scanning `examples/trip-planner` yields exactly the dependencies and env names listed in its README, with those `file:line` refs.
- A run with sockets blocked proves no network call (D20).
- The fake key appears in no excerpt, stored row, API response or log.
- Golden snippets per language.
- Excluded folders and URL-in-a-longer-string are ignored.
- Ids are stable across two scans.

**Why:**
- A dependency map is about *what* the app uses, not the order it runs in. Gates and critical paths belong to flow maps.
- Keeping the `Planner` interface means the map, versions and diff built in Phase 3 work for real repos with no new UI plumbing.
- The confirmed/unconfirmed split lets the scan stay generous without presenting a link in a README-like string as a service.
- Separating coding-tool MCP servers stops a developer's own agent setup from being mistaken for the app's architecture.

**Code:** `scan/` (new), `flowmap/models.py` (`Flow.kind`, `Analysis.scan`), `flowmap/validate.py`, `flowmap/planner.py` (`ScanPlanner`), `connectors/presets.py` (SDK → service table), `cli.py`, `api/flowmap.py`.

## D22. Scanner rules learned from the first real scans (Phase 4)

**Supersedes, in D21:**
- "Hosts of the same site stay separate entries, and the map groups them by site";
- the `skipped` keys in D21's example output.

Everything else in D21 holds. These rules came from scanning a real Flutter repo (`smart-travel-assistant`) and from the Phase 4 review, before any of D21 shipped.

**Choice:**
- **Merging.** Hosts of one known service merge into one entry, `api-<service id>`. For example, Wikimedia's `thumb.`, `commons.` and `upload.` hosts are one Wikimedia. Unknown hosts stay one entry each.
- **Hidden folders are tooling, not the app.** In `.claude`, `.cursor`, `.github` and other dot-folders, only MCP config files are read. (The real repo carried a 107-file Claude Code skill that otherwise showed up as fake dependencies.)
- **A `www.` page stays unconfirmed even when the code opens it** (`launchUrl(Uri.parse(...))`), unless it looks like an API or is a known service. It's a link, not a call.
- **Evidence.**
  - At most 10 entries per dependency, plus `places`, a count of all of them.
  - Each place's label says what it shows: "calls it" only for a recognised call, otherwise "uses the address".
- **Targets stop before template parts** (`/driving/$path`, `/{z}/{x}/{y}.png`), so a check gets an address it can call.
- **What the excerpts mask.** Before storage they go through `security.logfilter.redact_code`, which masks:
  - known key shapes;
  - URL credentials (`user:pass@`) and query strings;
  - string values given to names containing key, token, secret, password or credential.

  It's pattern-based: it catches known key formats and these shapes, not everything.
- **`via`** is recorded only when a host is reached *only* through one MCP server.
- **MCP scope.** If code names one server of a config, the whole config is the app's. A server name counts only when code that imports `mcp` passes it to a call, so a common word like "time" elsewhere doesn't make a config the app's.
- **Router SDKs.** LiteLLM is resolved per model name by prefix (`anthropic/…` → Claude). The prefixes live in `presets.MODEL_PREFIXES`.
- **Skipped files are counted by reason:** `ignored` (tests, docs, tool folders), `binary`, `too_big`, `outside` (a symlink leaving the folder), `unparsable`. Vendored and build folders are pruned and not counted. Configs count as `json` in `languages`.
- **Choosing the folder.**
  - One repo per database, kept in the `settings` table.
  - `POST /scan` and `flowforge --repo PATH` follow the same rule: the same folder keeps its map; a different folder starts a fresh map only with `replace: true` / `--replace`. Without it, the API answers 409 and the server refuses to start.
  - A chosen folder with no map yet is drawn at start-up.

**Why:** a scanner is only useful if its map can be trusted on real repos. Each rule here removes a false dependency, a false confirmation or a possible leak that a real repo or the review actually showed.

**Code:** `scan/`, `security/logfilter.py` (`redact_code`, `SECRET_WORDS`), `connectors/presets.py` (`SERVICES`, `ROUTER_SDKS`, `MODEL_PREFIXES`), `api/scan.py` (`choose_repo`, `startup_repo`), `storage.py` (`FlowStore`, `settings`), `flowmap/service.py` (`map_folder`), `cli.py`.

## D23. No hand-drawn maps, and the phases after the first look (Vishwa, 2026-10-21)

**Supersedes:**
- in D21, "Example mode shows two maps, switchable";
- in D21, the list of skipped test folders (extended below);
- in D19, the roadmap order from Phase 6 on.

Everything else in D21 and D22 holds.

**Context.** Vishwa used Phase 4 on the sample and on `smart-travel-assistant`. Three things stood out:
- The Dependencies | Flow switch put two different apps under one switch. The Flow side, Baby-care, was drawn by hand, yet its header said the Planner drew it from your code.
- A real repo's fake-data file (`lib/dev/fake_recommendations.dart`) became a dependency.
- Once a map existed, the dashboard had no way to scan another folder.

Vishwa also restated the goal: an MCP management tool that works out the critical path and the most efficient way for the code to use its dependencies, and later works next to coding agents.

**Choice:**
- **Every block and line on a map comes from the user's code (`file:line`) or from the user's own edit.** Nothing is drawn by hand or invented, in example mode too.
  - Example mode shows one map: the trip planner's dependency map.
  - The Baby-care flow map and the switch leave the dashboard.
  - The Baby-care fixture stays as test data for the flow-map code (gates, critical path, replay), which flow order from code reuses.
  - The API keeps `?map=flow`. It is empty until flows come from code.
- **Fake and test data files are skipped like test folders,** and counted as `ignored`:
  - file names starting with `fake_`, `mock_` or `dummy_`;
  - test files: `test_*.py`, `*_test.py`, `*_test.dart`, `*.test.*`, `*.spec.*`;
  - folders `fixtures/`, `mocks/`, `__mocks__/` and `fakes/`.
- **A dependency's `target` is the address a check will call.** It comes from the host most of its URLs use. With several URLs on that host, it is their longest shared path up to a `/`. So a page on `commons.` plus nine images on `thumb.` give `https://thumb.wikimedia.org/wikipedia/commons/thumb/`, not the first URL.
- **Local blocks are named for what they run:** the script's file name without folder or extension, with `_` and `-` as spaces (`tools/packing_list.py` → "packing list"). The full command stays the target.
- **"Scan a folder" is always in the map's header.**
  - The same folder re-scans as before.
  - A different folder replaces the map after the user confirms. The old folder's versions are deleted, as with `--replace` (D22).
  - In example mode it shows the command instead (`flowforge --repo <folder>`), because example data and real data never mix (D16).
- **Roadmap from Phase 6 on:**
  - **6, flow order from code:** Python first, through the AST. A call that uses another call's result depends on it, and every line keeps its `file:line`. The result is a real DAG. Its critical path is weighted by Phase 5's measured latencies, labelled as estimates. On top of it come suggestions like "these calls don't depend on each other: run them together, about N ms saved".
  - **7:** security findings.
  - **8:** launch.
  - **9:** CLI agent + Tauri.
  - **10 (V2):** coding agents. A suggestion from Phase 6 is one of the changes an agent can make, on a branch, behind a gate.
  - **11:** FlowForge's own small language model (SLM), run locally with guardrails, replacing the dependence on hosted APIs such as NIM for anything FlowForge itself needs an LLM for. Plain code stays the source of truth. The SLM's proposals are data, checked against the code before they reach a map (D14), and it sees masked findings only (D20).

**Why:**
- A map the user cannot trust is worse than no map. A hand-drawn graph can show services the code never calls.
- The critical path and "run these together" turn the map from a picture into advice, which is what an MCP management tool owes its user. It needs flow order, so flow order moves ahead of security and launch.
- Owning the model removes the last outside service FlowForge itself relies on.

**Code:** `main.py`, `example_data.py`, `scan/files.py`, `scan/scanner.py`, `frontend/src/flowmap/FlowMapPage.tsx`, `CLAUDE.md` (roadmap).

## D24. Health checks: what a check is and how it runs (Phase 5, Vishwa, 2026-10-21)

**Context.** D19 asked for "Check now" with generic checks per kind and results stored over time. Vishwa's answers:
- **Timer:** not sure yet. This phase has none; checks run when the user presses the button.
- **Keys:** only if it's safe. No check reads or sends a key.

**What gets checked.** The current dependency map, with the user's edits:
- confirmed blocks, including the "Your coding tools" group (D21);
- not hidden blocks;
- not unconfirmed blocks, which show grey: "not checked: unconfirmed".

**One check per kind.** Results are `up` (green), `warn` (amber) or `down` (red), with a latency and a short reason that passes through the redactor. Response bodies are never kept.

**When a request can't connect, the check says why, step by step.** It asks:
- does the name resolve (DNS)?
- does each of its addresses, up to 4, accept, refuse or ignore a connection on the port?
- if the port is open, did the secure connection fail?

Only the name, the addresses and the port are used, and nothing else is sent. The answer goes in plain words, with a likely fix. For example, "both of its addresses refused connections on port 443" means the service is down or blocking this computer. The dashboard adds "your internet works" when other dependencies answered when last checked.

A dependency with nothing to check is `skipped` (grey) and says why. Two cases:
- the code holds no address for it (an SDK such as Supabase, whose URL comes from config at runtime);
- its MCP arguments include a masked secret, which FlowForge won't fill in.

| Kind | What it does | up | warn | down |
|---|---|---|---|---|
| API | One GET to the target: no key, cookie or query; a FlowForge User-Agent; 10 s timeout | any answer below 500. A 401 or 403 means "up, needs a key" | slower than 2 s; plain `http://`; or a TLS certificate that expires within 14 days | no answer, a DNS failure, a timeout, or a 5xx |
| LLM | Its model list: Ollama `/api/tags`, OpenAI-compatible `{base}/models` | reachable, and the model is listed (or a key is needed to see the list) | the model isn't listed; slower than 2 s; plain `http://` to a host that isn't this machine | not reachable |
| MCP, stdio | Start it in the repo folder with the MCP SDK's minimal environment (none of the user's own variables), list its tools, stop it; 30 s timeout | tools listed | took over 5 s | didn't start or couldn't list tools. The reason is the error and the last lines of its stderr, redacted, plus the env var names its config names |
| MCP, remote URL | As an API | | | |
| Local | The script exists in the repo, or the program is on `PATH`. **It is never run** | found | | missing |

**Starting an MCP server runs code.** That code is a script in the repo, or an `npx`/`uvx` package fetched from npm or PyPI.
- The first "Check now" lists exactly which commands will start, and the user confirms.
- Each yes covers exactly the commands that were shown. "Check this one" on one server confirms that server only. A re-scan or an edit that changes a command asks again.
- Without it, `POST /checks` answers 409.

**How checks run (D19: the scheduler runs them).**
- `StepType` gains `"check"`, an additive change, and `CheckNode` runs one check per step.
- A check run is a workflow with:
  - one step per dependency and no edges;
  - `retries: 0`, because a retry would hide flakiness;
  - no cache;
  - at most 8 checks at once, 3 of them MCP servers.
- It starts through the existing `start_run`, so its progress streams over the existing SSE and the run is stored (D16).
- **A dependency that is down is a result, not a failed step.** The step succeeds with `{status: "down", reason}`. A step fails only when the check itself breaks.

**Storage.** Table `checks`, one row per dependency per check: `run_id, dep_id, kind, status, latency_ms, summary, detail, at`.
- Rows are written when the run ends, from its events, so a stopped run keeps the checks that finished.
- A check that breaks (a FlowForge bug) is recorded as `skipped`, "The check couldn't run", never as the dependency being down. A check that never ran records nothing.
- Every check is kept; there is no pruning yet.
- Choosing a different repo (D22) clears the history and every yes.

**Timeouts.** At most 3 MCP servers start at once. That limit sits in the check node, because the scheduler's slots are per step type. So an MCP step's timeout covers its wait for a turn: 30 s for each round of 3.

**Connectors.** "Test connection" on an LLM or HTTP connector makes the same one request as its check, without the key.

**Example mode stays offline (D16).** "Check now" returns recorded results, labelled as example results, and sends nothing. The trip planner's broken `currency` server records its real error.

**Later, opt-in, not built now: authenticated checks.**
- The key is read from `.env` only at check time.
- It is sent only to the dependency's own host from the code.
- It is never stored, logged or shown.
- The user turns it on per dependency.

**Defaults.** These numbers are FlowForge's choices and may be tuned:
- slow means over 2 s for an API or LLM, and over 5 s for an MCP server;
- 14 days of certificate left;
- 10 s and 30 s timeouts.

**Why:**
- A check that needs no key and runs nothing it doesn't have to is safe to press on any repo.
- Running checks through the scheduler gives live progress, stored history and concurrency limits for free. Their latencies become Phase 6's critical-path weights.
- Asking before starting MCP servers keeps the promise that FlowForge never runs your code behind your back.

**Code:** `checks/` (new), `nodes/check_node.py` (new), `schema.py` (`"check"`), `storage.py` (`checks`), `api/checks.py` (new), `connectors/presets.py` (LLM health paths), `example_data.py`, `frontend/src/`.

## D25. Flow order from code: the critical path and "run these together" (Phase 6, Vishwa, 2026-10-21)

**Supersedes:**
- in D17, policy gates, for flows read from code only;
- in D23, "The API keeps `?map=flow`. It is empty until flows come from code": flows now come from code.

**Context.** D23 made flow order the next phase. An MCP management tool should say:
- in what order the app calls its dependencies;
- which chain makes it slow;
- what could run at the same time.

D23's rule holds: nothing drawn by hand. Vishwa chose Python first, with Dart and JS/TS as the next step.

**Choice:**
- **Source.** Python, read by the stdlib `ast`. Nothing is run or sent, and no LLM is used (D20).
  - A repo with no Python entry point shows "Flow order needs Python for now; Dart and JS/TS are next."
- **Entry points.**
  - An entry point is a function in the repo that reaches at least one dependency and that no other function in the repo calls.
  - A wrapper whose whole body is one call into another such function is unwrapped (`main` → `asyncio.run(plan(...))` → `plan`). FlowForge doesn't unwrap into a helper that makes its own calls (`weather()` calling an API itself): that helper is a step.
  - Each entry point is a `start` block, so one map can hold several flows.
- **Steps.** A statement in an entry function is a step when it reaches a dependency (D21) in one of four ways:
  - a scan evidence line inside it;
  - a module-level name whose definition line is evidence (a `client = OpenAI(...)`);
  - an MCP server's name passed as a string argument (D21's `via` rule);
  - an in-repo function call, followed transitively through imports.

  One block per step:
  - its kind and tile come from the dependency;
  - its evidence is the step's own `file:line`;
  - its title is the code's own label when there is one, otherwise the dependency's name.
- **Lines.**
  - **Data:** step B depends on step A when B reads a name A wrote, directly or through plain code in between. A method call on a name (`facts.append(...)`) writes that name.
  - **Control:**
    - a step inside `if cond:` depends on what defined `cond`'s names, and the `if` is a decision block with yes/no branches, its condition (`ast.unparse`) and its `file:line`;
    - an early `return` inside an `if` makes every later step depend on that decision.
  - **Order kept:**
    - two writing steps keep their written order. A write is an HTTP call other than GET or HEAD, or an MCP tool whose name starts with a write verb (`write_file`, `create_…`, `send_…`, `delete_…` …). The tool's name also sets `Op.read_only`;
    - steps the code already runs together (`asyncio.gather`, a `TaskGroup`, `create_task`) are drawn together;
    - a step inside a loop is marked "repeats".
  - **Readability:** lines are transitively reduced. Plain code is not drawn as blocks, but it still carries data dependencies between steps.
  - **One branch is enough.** An `if` without an `else` just carries on, so a decision on a code flow may show only its `yes` branch.
  - **Reached through a server.** A dependency the scan found only through an MCP server (D21's `via`), named inside the statement that calls that server, gets its own block off the server's block. It adds no time of its own.
- **No gates.** A flow read from code describes the user's app, not a run FlowForge executes. Side effects are marked, not gated (D17's gates stay for flows FlowForge runs). Call blocks need no connected app, as on dependency maps (D21).
- **Weights for the critical path** (`validate.critical`, D1, D5):
  - the dependency's latest check latency (D24), marked `measured`;
  - otherwise the per-kind default, marked `estimate`.

  LLM blocks are always `estimate`, because a check measures "is it up", not how long a reply takes.
- **Advice: run these together.** FlowForge compares the time as written with the critical path of the dependency graph. As written means source order, sequential except where the code already runs calls together.
  - Each group of steps that sit next to each other in the code, are awaited one after another and don't use each other's results becomes one piece of advice: the steps and their `file:line`s, how (`asyncio.gather`), and about how much time it saves.
  - When the code stops early if an earlier step fails (`if place is None: return`), the advice carries that caveat: starting a step earlier can waste a call.
  - FlowForge never changes the code. V2 (Phase 10) can hand advice to a coding agent, on a branch, behind a gate.
- **Model (additive):**
  - `Flow.source` (`planner` | `code`);
  - `Flow.advice` (`nodes`, `refs`, `text`, `saved_ms`, `caveat`). Advice below 50 ms is not shown;
  - `Flow.written_ms`, the time as written;
  - `FlowNode.repeats`;
  - `FlowNode.estimate_source` (`measured` | `estimate`).
- **Maps.**
  - The `flow` map is drawn by `CodeFlowPlanner`, from the chosen repo or, in example mode, from `examples/trip-planner`.
  - The Dependencies | Flow switch returns, because both maps now come from code.
  - Versions, re-scan → diff, overrides and positions come from D17 unchanged.
- **Limits, said in the UI.** These are missed or flattened, and the analysis says so instead of guessing:
  - calls passed around as values;
  - callbacks;
  - dynamic dispatch;
  - steps buried in other entry points' helpers.

**Why:**
- Saying "these four calls don't need each other, so run them together" turns a picture into advice.
- Reading it from the AST keeps D23's promise that every line can be proved.
- Reusing the Planner seam, `critical()` and the flow-map UI means the work is the analysis, not new plumbing.

**Code:** `flow/` (new), `scan/scanner.py` (`scan_with_places`), `flowmap/models.py`, `flowmap/validate.py`, `flowmap/planner.py` (`CodeFlowPlanner`), `main.py`, `example_data.py`, `frontend/src/flowmap/`.

## D26. Graph themes with motion, and the MCP Map: a standard picture to send (Phase 6, Vishwa, 2026-10-21)

**Context.** Vishwa approved two artboards (`docs/design/flow-artboards/themes.html`, `standard.html`) and asked for two things:
- graphs that look better, with motion, in themes users can pick;
- "a standard way to send someone your MCP architecture": an exportable graph, professional enough for reports.

**Choice:**
- **Themes, for viewing in FlowForge.** Five themes for both maps:
  - **Studio:** today's cards;
  - **Boxed:** blocks inside containers of what runs together;
  - **Blueprint:** outlines on a grid, with timings as dimension lines;
  - **Metro:** stations on lines coloured by kind, with the critical path as the main line;
  - **Soft:** calm colour fields by kind.

  Every theme keeps the same meanings: health colours (D24), the critical path as the thickest line in the theme's ink, and measured versus estimated weights (D25). A theme menu sits on the map. The choice is kept per viewer in the browser, as a viewer convenience; FlowForge itself doesn't store it.
- **Motion that explains, never decorates.**
  - Lines draw themselves in once, in call order.
  - **Watch it run** (code flows) replays the "could be" schedule (each call starting as early as its inputs allow, weighted as in D25) through the existing replay engine (D17), with a train on each line while its call runs. It is labelled as the schedule, not a recording.
  - Hovering a block lights what it waits for and what waits for it.
  - Reduced-motion settings turn all of it off.
- **The MCP Map, for sending (rules v1, written up in `docs/mcp-map.md`):**
  1. **Lanes are kinds,** always in this order: decisions, LLMs, MCP servers, APIs, local programs.
  2. **Time runs left to right.** A call starts when its inputs are ready, and its bar is as long as it takes. A dependency map has no time, so its blocks sit in lanes in name order.
  3. **One shape per kind,** readable without colour: a double ring for an entry point, a ring with a dot for an LLM, a hexagon for an MCP server, a rounded square for an API, a triangle for a local program, a diamond for a decision.
  4. **Lines:**
     - the thick line is the critical path;
     - a dashed line means reached through another server;
     - a dashed bar is an estimate.
  5. **Marks:** a dot is health (teal up, amber needs a look, coral down), ✎ writes, ↻ repeats.
  6. **Every block has a source:** the Flow JSON behind the map gives each one's `file:line`.

  A title block (the app, where it was read from, the date, the counts) and a key go on every map.
- **Exports, made in the browser from the map's own data** (no server round trip, nothing sent anywhere):
  - **SVG:** the map itself, fonts named with system fallbacks;
  - **PNG:** at 2×, for slides;
  - **PDF:** through the browser's print dialog, from a print layout (A4 landscape);
  - **Mermaid:** a `flowchart LR` that GitHub renders in a README, keeping shapes, `yes`/`no` branches, `==>` for the critical path and `-.->` for through-a-server;
  - **Flow JSON:** the map's data with every block's evidence.

  Evidence excerpts are already masked (D22, `redact_code`); an export never contains a key value.

**Why:**
- A picture that follows fixed rules can be compared across apps and read without FlowForge. That is what makes it worth sending.
- Themes are a matter of taste. The MCP Map is a matter of agreement, so it gets rules and the themes don't.

**Code:** `frontend/src/flowmap/` (themes, motion, Metro and Boxed blocks), `frontend/src/mcpmap/` (new: layout, SVG, Mermaid, exports, `/map/export`), `docs/mcp-map.md` (new).

**Settled while building (2026-10-21), after the two-axis review:**
- Rule 3 also has a **filled square for a stop** (the code returns early), as `docs/mcp-map.md` already said.
- The export page offers **light or dark paper**; the file you download is the paper you see. Mermaid adds a stroke colour per kind (`classDef`), and the shapes still carry the meaning without it.
- ✎ on the MCP Map, and "Writes something" in the step panel, follow D25's rule: a method other than GET or HEAD, or an MCP tool that isn't read-only. D17's wider rule (every local program, any block with no method) stays for gates on flows FlowForge runs.
- Words taken from the code (a decision's condition and question, a call's label) are masked like evidence (`redact_code`) before they are stored, so an export can't carry a key from an `if`.
- Focusing a block with the keyboard traces its path, as hovering does.
- Not built yet: Blueprint's timings as dimension lines (it has the grid and the outlines).

---

## D27. Advice you can act on: the code change, and a prompt for your coding agent (Phase 6, Vishwa, 2026-10-21)

**Context.** Vishwa, on the Faster panel: "what's the point of advice if it's just there to say 'start these'? How is the user supposed to start them?" D25's advice names the calls and the saving, not the change.

**Choice:**
- **The change, written out, when plain code can write it safely.** For async calls in one block of one function, each a plain `x = await …` or `await …`, with nothing in between that reads their results or changes what they read: one `asyncio.gather` in place of the first of them, with the rest removed. The card shows the lines as they are and as they would be, each with line numbers, masked like evidence (D22). Copying the new lines is one click.
- **Partial when it has to be.** Calls of the same piece of advice that sit in another block (an `if`, a `with`, a `try`) are listed under "move by hand", each with its `file:line` and why ("inside `if sight:`"). The card says how much the written change saves on its own.
- **Never applied.** FlowForge doesn't edit the user's code (D19, section 9.3). The change is text to copy.
- **A prompt for a coding agent.** Every card has "Copy prompt": the file, the function, each call's line and words, the saving, the caveat (D25), and "keep the behaviour the same; change nothing else; run the tests". It names no key and quotes no code beyond the masked lines. This is the hand-off V2's agents (Phase 10) will take over.
- Synchronous calls get no written change (a thread pool changes too much to write blind); they get the prompt.

**Why:** advice that ends in "do it yourself" is a to-do, not help. A written change for the safe case, and a precise prompt for the rest, turn it into a minute's work, while the user's code stays the user's.

**Code:** `backend/flowforge/flow/rewrite.py` (new), `flow/advice.py`, `flowmap/models.py` (`Advice.change`, `Advice.prompt`), `frontend/src/flowmap/Faster.tsx`.

---

## D28. Two brains, both optional: the user's coding agent first, through FlowForge as an MCP server (Vishwa, 2026-10-21)

**Context.** Vishwa and a friend: users either use FlowForge's own LLM (NIM, another API wrapper, later the SLM of Phase 11) or "their brain", the coding agent they already have (Claude Code, Codex, Antigravity), connected to the project. Vishwa prefers the second and wants FlowForge to offer the connection.

**Choice:**
- **The core needs no brain.** Scan, maps, checks, the critical path and the advice are plain code (D20, D25, D27) and stay that way. Neither brain is ever required.
- **Brain B, the user's coding agent, is the default for AI work.** It runs on the user's own subscription and already has the repo, so FlowForge pays nothing and holds no extra code.
- **The connection: FlowForge is itself an MCP server.** One entry in the agent's MCP config (for example `.mcp.json`) starts it. Its tools, read-only first:
  - `get_map` (the dependency map and the flow);
  - `get_advice` (D27's changes and prompts);
  - `run_checks` (D24);
  - `get_security_findings` (Phase 7).

  The agent makes changes on a branch; FlowForge re-scans to confirm; the user approves every change (D11 gates, Phase 10). FlowForge never edits code itself.
- **Brain A, FlowForge's own LLM, is the fallback** for users with no agent: today NIM or another provider the user picks, seeing masked findings only (D20); later FlowForge's own SLM (Phase 11).
- **Safety:** whatever the agent gets from FlowForge is masked like evidence (D22); no key value, ever. Tool descriptions and repo text are untrusted input (section 6.5).
- **Delivery:** each piece ships on its own branch and PR (the MCP server, then each later brain feature), not bundled into another phase.

**Why:** an MCP management tool that is itself an MCP server is the natural way in for the agents developers already use, and it keeps FlowForge free and private by default.

**Code:** not yet. Planned as its own branch (`feat/mcp-server`) after Phase 6 is merged; plan mode first.

---

## D29. The FlowForge MCP server: five tools, the same data, nothing written (Vishwa, 2026-10-22)

**Context.** D28 makes the user's coding agent the default brain, connected through FlowForge as an MCP server. This decides what that server is.

**Choice:**
- **`flowforge mcp [--repo PATH]`**, a stdio MCP server (MCP SDK 2.x `MCPServer`), started by the agent itself. `--repo` defaults to the working folder the agent starts it in. It does not need the dashboard to be running.
- **The same data as the dashboard.** It opens the same database (`FLOWFORGE_DB`, else the default next to the checkout) and reads the saved check latencies and the saved yes for MCP commands. The map and the flow are read fresh from the repo each call (plain code, D20), so an edit shows up at once.
- **Five tools:**
  - `get_map`: the dependencies, each with its kind, address, `file:line` places and latest health;
  - `get_flow`: the calls in order with `file:line`, the decisions, the critical path, as written vs could be;
  - `get_advice`: D27's advice, with the written change and the agent prompt;
  - `check_health`: D24's checks, now;
  - `what_changed`: the repo now compared with the map saved in the dashboard (dependencies added or removed) and the flow's could-be time.

  `get_security_findings` comes with Phase 7.
- **Annotations:** every tool is read-only; `check_health` is marked open-world (it makes requests).
- **Safety:**
  - Every answer goes through the same masking as evidence (`redact_code`, then the `Redactor` with the configured key values). No key value, ever.
  - `check_health` starts an MCP server only when the dashboard already holds the user's yes for that exact command (D24's confirmation); otherwise that check is "skipped: say yes in the dashboard first". APIs, LLMs and local programs get D24's harmless checks.
  - There are no write tools. The agent edits; the user approves (D28).
  - Logs go to stderr only, so the stdio pipe stays clean.
- **Proof it works:** each tool call stores the time and the tool's name (a setting, no arguments). The dashboard's "Connect an agent" page shows it, with copy-ready set-up for Claude Code, Codex and Antigravity, paths filled in. A format that couldn't be checked against the agent's current docs is labelled so.

**Why:** a server the agent starts by itself, reading the same saved data, is one config line for the user and keeps one source of truth. Read-only tools and the existing yes-before-start rule keep FlowForge's promises when an agent, not a person, is asking.

**Code:** `backend/flowforge/agent/` (new), `cli.py` (`mcp`), `api/agent.py` (`GET /agent/connect`), `frontend/src/agent/ConnectAgent.tsx`.

---

## D30. The Connect page: what your agent gets, and what it asked (Vishwa, 2026-10-22)

**Context.** D29's Connect page was a long command, a text list of tool names and a thin "last call" line. Vishwa found it hard to read and chose a layout from mock-ups: set-up on the left; on the right, what the agent will get from this repo, and, once it has called, what it asked. A sample chat was rejected: FlowForge has no chat, and a made-up conversation would mislead.

**Choice:**
- **Left, set-up:** the three agents as cards (brand marks per D15; a monogram where `simple-icons` has none), one Copy button, the command itself behind "Show the command", three numbered moves, the connection state.
- **Right, top: "What your agent gets".** One card per tool with the question it answers and its answer for this repo now: the dependencies and their kinds, the latest health (from stored checks; nothing is run), as written vs could be, the advice's count and time saved. `GET /agent/preview` builds them with the same code as the tools, through the same masking. `what_changed` has no number before an edit, so its card only says what it is for.
- **Right, below, after the first call: "What your agent asked".** Each tool call stores `{tool, repo, at, got}`, newest first, the last 20 (replacing D29's single last call). `got` is a one-line answer made from counts and times only (for example "11 dependencies", "9 up · 1 down"), never names, addresses or code, and it is masked too.
- The headlines on the cards and in the list come from one function, so the two can't disagree.

**Why:** the page should show what connecting gives you before you connect, and prove it worked after, without a paragraph or a fake screenshot.

**Code:** `agent/server.py` (`headline`, `preview`, the call list), `api/agent.py` (`GET /agent/preview`, `calls`), `frontend/src/agent/ConnectAgent.tsx`.

---

## D31. Security findings from the scan (Vishwa, 2026-10-22)

**Context.** Phase 7. The scan already reads every file the map comes from; it should also say what in them is unsafe. CLAUDE.md §6.4 step 1 gives the finders (known key shapes, entropy, the AST), and §6.5 the rule that a value is never kept or shown.

**Choice:**
- **Five findings in V1,** found by plain code in the same pass as the scan (D20: nothing sent anywhere):

  | Kind | Level | Found when |
  |---|---|---|
  | `key_in_code` | high | a known key shape (the `KEY_PATTERNS` of `security/logfilter.py`, each with a name) on any line, comments included; or a string of 16+ characters with high entropy (≥ 3.5 bits a character) given to a key/token/secret/password name (Python by the AST, JS/TS/Dart by patterns). Placeholders (`your-…`, `<…>`, `xxx`, `changeme`, `example`…) and env lookups are not keys |
  | `key_in_config` | high | an MCP config's `env` holds a literal value under a key-like name, rather than a reference (`${VAR}`) |
  | `plain_http` | medium | an API or LLM the app calls over `http://` on a host that isn't local |
  | `unpinned_server` | medium | an MCP server started by `npx`/`uvx` whose package has no version (`pkg@1.2.3`, `pkg==1.2.3`) |
  | `broad_files` | medium | a filesystem MCP server given `/`, `~`, `$HOME` or a drive root |

  Files the scan skips (tests, fake data, vendored code: D21, D23) are not searched. `low` exists for later kinds; none uses it yet.
- **A finding is** `{id, kind, level, title, ref, dep_id, excerpt, first_line, fix, prompt}`. `id` is stable (`kind-path-line`). `excerpt` is the masked lines around `ref`, like evidence. `fix` is one sentence; `prompt` is the whole change for a coding agent, built by code (D27's rule). **The matched value is never kept**: it lives only in the scan's memory while the file is read.
- **The dependency it belongs to:** the dependency with a place on the same line; for a key, else the dependency with a place within three lines of a line that uses the key's name. Otherwise none, and the finding stands alone.
- **Where it shows:** `ScanResult.findings` (stored with the map's scan, so a re-scan updates it); `GET /security`; the Security page (counts by level, one card per finding with its excerpt, fix, Copy prompt and Show on map); a badge on the map's blocks that have findings and a list in their step panel; a sixth read-only MCP tool `get_security_findings` and its card on the Connect page (D30).
- **Honest wording:** "catches known key formats and these patterns, not everything" (§6.1). The fix for a key always says to replace it, because it may be in git history; FlowForge doesn't read the history.

**Why:** the same pass and the same masking as the scan keep one source of truth and one privacy rule. Findings are data with a fix and a prompt, never actions: FlowForge doesn't edit code (D28).

**Code:** `security/finders.py`, `security/findings.py` (new), `scan/models.py` (`Finding`), `scan/scanner.py`, `scan/mcp_config.py`, `api/security.py`, `agent/server.py`, `frontend/src/security/`.

---

## D32. Flow order for Dart, JavaScript and TypeScript (Phase 6b, Vishwa, 2026-10-23)

**Context.** D25 reads the order of calls from Python's AST. Dart (Flutter) and JS/TS apps got "needs Python". The plan Vishwa approved: a small reader of our own for the three languages (they share braces and `;`), no new dependency, the same flow, critical path and advice, and an honest label.

**Choice:**
- **`flow/curly.py` reads Dart, JS and TS** without running anything. It first blanks out comments and string contents (keeping `${…}` and Dart's `$name` interpolations as code, so what a string reads still counts), then finds:
  - functions: Dart declarations and getters, `function` and arrow functions, class methods; each with its class, whether it is `async`, and its body;
  - statements in order: declarations (`final/var/const/let/late`, typed or not, and destructuring), assignments, `if/else`, loops, `try/catch/finally`, `switch` (one statement), `return/throw`. JS without `;` ends a statement at a line break when nothing continues it;
  - what each statement reads and writes (D25's rules: names it reads, names it declares or assigns, a list it adds to), whether it awaits, and whether it already runs calls together (`Future.wait`, Dart's `(a, b).wait`, `Promise.all/allSettled/race`).
- **What it calls:** a statement reaches a dependency when one of the scan's call places (D21) is inside it; when it calls a function of the repo that reaches one (by name: the same file first, then a name unique in the repo; `Class.method` for a static call); or when it uses a known service's client. A service's client is named by `presets.SERVICES` (`client`: for Supabase `Supabase.instance.client` and `createClient(`), and any name the repo binds to it (`SupabaseClient get supabaseClient => Supabase.instance.client;`) is that client too.
- **The same flow as Python's:** the builder, the critical path, the decisions with whole questions (`if (trip == null) throw …` asks 'Did "get trip" fail?'), early stops, the advice and its caveat are shared; only reading the code differs. A step's label is the repo function it calls, as words (`getItineraryItems` → "get itinerary items"), or a string it passes.
- **The written change (D27):** Dart `final (a, b) = await (f(), g()).wait;` (it needs `import 'dart:async';`), JS/TS `const [a, b] = await Promise.all([f(), g()]);`. The same safety rule as Python: one block of one async function, each a plain `x = await …`, nothing between them using a result or changing an input. A TypeScript declaration with a type is listed to move by hand, so no type is dropped. `Change.import_text` names the import to add.
- **Honest label:** `Flow.patterns` lists the languages read by patterns; the Faster panel says they are less exact than Python. Mixed repos get one flow with every language's entry points.
- **Hidden order, learned from the first real Flutter app** (three of its four first pieces of advice were wrong):
  - a call to a repo function carries the outside names (fields, globals) that function reads and writes, through what it calls: `loadTrips()` filling `_trips` comes before a line that reads `_trips`;
  - a service call that changes state (`insert`, `update`, `upsert`, `delete`, an `.auth.…()` call such as signing in) is a write, and a call that reads and writes one service counts as a write, so two of them keep their order (D25);
  - a callback's calls (an anonymous function passed somewhere) run later, not as part of the statement, as D25 already skips Python's lambdas; a statement that gathers (`Future.wait`, `Promise.all`) runs its callbacks now, so those count.
- **As written, per entry point (amends D25's `written_ms`):** entry points are separate actions, so "as written" is the slowest entry point's calls one after another, not every entry point added up. With 37 entry points the sum read 14.4 s against a 1.2 s critical path, which oversold the saving.

**Why:** the same plain-code reading (D20) and the same map for every language the scan already knows, without a parser dependency. tree-sitter stays the option if patterns prove too loose (CLAUDE.md §12).

**Code:** `flow/curly.py` (new), `flow/__init__.py`, `flow/advice.py`, `flow/rewrite.py`, `flowmap/models.py` (`Flow.patterns`, `Change.import_text`), `scan/scanner.py` (`Places.code`), `connectors/presets.py` (`client`), `frontend/src/flowmap/Faster.tsx`.

---

## D33. Declutter: three visible controls, the rest one click away (Vishwa, 2026-10-23)

**Context.** Vishwa: the extra information on the screens "makes our app cluttered and useless", and a whole Security page is too much for "a key is exposed". The map's header had 9 buttons and a provenance badge, the toolbar wrapped onto two rows, every block carried a kind tag and its `file:line`, the legend and minimap were always on, the side panel had six sections, 32 places showed decision numbers such as "(D25)" to users, and a Flutter app's flow stacked 37 actions with UI-only checks. Supersedes the page and layout parts of D17, D24, D26, D30 and D31 where they disagree; their data and APIs stay.

**Choice:**
- **The rule for every screen:** a header with the name, the view switch, at most one warning and one main action, and a ⋯ menu; the page shows only what answers "what is it, and is it all right"; details appear on hover or click, never printed by default; no internal words (decision numbers, "Flow v1", "fact sheet").
- **Map:** header = repo name (with "Example" as a small chip), Dependencies / Flow, the ⚠ findings chip, Check now, ⋯ (style, re-scan, scan another folder, my edits, add dependency, export, legend, minimap, how it was mapped). Blocks show a name, the service and the health dot; `file:line` shows on hover and in the panel. Zoom, fit and search sit small in a corner. The legend and minimap are off until chosen in ⋯.
- **Flow: one action at a time.** An action picker lists the entry points, slowest first, with their times; the map draws the chosen one (the slowest by default). Decisions are drawn as small ◆ marks on the line, with their question on hover and click; "Show every check" in ⋯ brings back the full boxes. A decision that only reads UI state (`mounted`, `context`, a field compared to a local) and guards no service call isn't drawn.
- **Faster panel:** the two times and their bars, Watch it run, then one card per piece of advice with its saving, Show the change and Copy prompt. Caveats, the critical path and the limits are behind an ⓘ.
- **Side panel:** three parts: a warning if any (with Copy fix prompt), health (with Check), and the code (folded). Rename and Hide sit behind ⋯.
- **Security on the map:** the ⚠ chip (hidden when there is nothing to fix) opens a short list: level, title, `file:line`, Copy fix, Show. No key value is shown anywhere, so there is no password page: there is nothing secret to protect. The Security page and its rail button go; `GET /security` and `get_security_findings` stay.
- **Rail:** Map, Checks, Connect agent, then Theme. The catalog and Add app open from the map's ⋯ → Add dependency (their routes keep working). The Checks page loses its squares strip and keeps the table.

**Why:** a first look decides whether a stranger keeps FlowForge. Three controls and one idea per screen make the map readable at a glance; nothing is removed, only moved one click away.

**Amended the same day (Vishwa):** a bare ⋯ hid too much: the map lost options people reach for. The map's header now shows **Re-scan, Export and Style ▾** as buttons next to the warning chip and Check now, and the menu is labelled **More ▾** and keeps the rest (scan another folder, my edits, add, apps, how it was mapped, re-tidy, critical path, every check, file:line, legend, minimap). Whether this or the old full row reads better is to be seen in use.

**Code:** `frontend/src/flowmap/` (`MapHeader.tsx`, `MoreMenu.tsx` new; `FlowMapPage.tsx`, `nodes.tsx`, `Faster.tsx`, `StepPanel.tsx`), `frontend/src/security/SecurityChip.tsx`, `components/Shell.tsx`, `checks/ChecksPage.tsx`, `flow/curly.py`, `flow/__init__.py`.

---

## D34. An installable package (Phase 8, part 1, Vishwa, 2026-10-24)

**Context.** Phase 8 is split: make FlowForge installable now and quietly, add features, then announce. Until now it ran only from a checkout: the dashboard, the example app, the sample workflows and the default database were found next to the source, and the Connect page told agents to run `uv --directory <checkout> run flowforge mcp`. The name `flowforge` was free on PyPI.

**Choice:**
- **One package, `flowforge`, with everything it needs inside:** the built dashboard (`flowforge/_dashboard`), the trip planner for `--example` (`flowforge/_example/trip-planner`, its tracked files only), the sample workflows (`flowforge/_workflows`) and the classic page. `home.resource(name)` finds each inside the package, else in the checkout, so development works as before. No Node is needed to run it.
- **Where data lives:** in a checkout, `flowforge.db` stays next to it; installed, the default is `~/.flowforge/flowforge.db` (`FLOWFORGE_HOME`), never inside the installed package. `FLOWFORGE_DB` still wins.
- **The agent's command (D29) follows how FlowForge was installed:** a checkout keeps `uv --directory …`; a `uvx` install gives `uvx flowforge==<version> mcp …`, pinned, as FlowForge itself advises for MCP servers (D31); a `pip` install gives the same Python running `-m flowforge.cli mcp …`.
- **`flowforge --version`.**
- **Releases by tag, with no stored secret:** pushing a `v*` tag runs `release.yml`: build the dashboard, build the wheel and sdist, install the wheel in a clean environment outside the repo and smoke-test it (version, `--example` serves the page and the map, `flowforge mcp` answers), then publish to PyPI with trusted publishing (PyPI trusts this repository's workflow; no token or password exists to leak). Every PR runs the same build and smoke test without publishing.
- **Vishwa owns the PyPI project:** the account, its 2FA and the trusted publisher are set up by him.

**Why:** one command (`uvx flowforge-map --example`) is the difference between a stranger trying FlowForge and not. Packaging the same files the checkout uses keeps one code path; trusted publishing keeps the "no secret anywhere" promise for the release itself.

**The name on PyPI is `flowforge-map`** (same day): PyPI refused `flowforge` as too similar to an existing project, `flow-forge` (an empty placeholder, v0.0.0). The brand stays FlowForge; the command is `flowforge` (and `flowforge-map`, so `uvx flowforge-map` runs it); the agent's uvx command pins `flowforge-map==<version>`. A clean brand name can still be chosen before the announcement (CLAUDE.md §12, question 1).

**Code:** `home.py` (`IN_CHECKOUT`, `resource`, `database_path`), `spa.py`, `cli.py`, `main.py`, `api/scan.py`, `api/agent.py`, `pyproject.toml`, `.github/workflows/release.yml`, `.github/workflows/ci.yml`.

---

## D35. A map made by an older FlowForge is read again (Vishwa, 2026-10-24)

**Context.** Vishwa's Flutter app showed all 37 actions stacked with every UI-only check: its flow had been saved the day before D33, and FlowForge only draws a map when there is none, so a saved map never benefits from a newer reader. Anyone upgrading the package would see the same.

**Choice:**
- Every map records the version of the reader that made it (`Flow.reader`, from `flowmap.planner.READER`). The number goes up whenever a change to the scan or the flow reader changes what a map holds.
- On start, a map whose `reader` is older than the current one is read again from the folder and saved as a new accepted version. Nothing in your code changed, so there is nothing to review; the older versions stay listed, and your edits (overrides) and saved positions are kept, since they are stored apart from the map.
- A map from the current reader is left as it is, so starting FlowForge never adds versions by itself otherwise.

**Why:** an upgrade should show the better map without the user finding "Re-scan" first.

**Code:** `flowmap/models.py` (`Flow.reader`), `flowmap/planner.py` (`READER`), `flowmap/service.py` (`first_map`).

---

## D36. Keys the coding agent never sees (Vishwa, 2026-10-24)

**Context.** A map that only points at problems isn't enough. Keys are the problem people hit most when a coding agent adds a dependency:
- they paste the key into the chat;
- or they leave it in a `.env` the agent reads;
- or they leave it in the code.

The agent only needs the key's **name**: the code it writes reads `os.environ["STRIPE_SECRET_KEY"]`. Vishwa proposed a sign-in with 2FA to view the keys; we chose not to (below).

**Choice:**
- **Three ways in, one store.**
  - `flowforge key add NAME`, typed hidden (`getpass`).
  - The dashboard's password box (`PUT /keys/{name}`, the "form door" of §6.2).
  - `flowforge key import [.env]`.
  
  Each saves the value in `security/keystore.py`:
  - the OS keychain (`keyring`: macOS Keychain, Windows Credential Manager, the Secret Service on Linux), under the service `flowforge:<repo path>`;
  - else a Fernet-encrypted file in `FLOWFORGE_HOME/keys/`, whose key is `FLOWFORGE_MASTER_KEY` or `FLOWFORGE_HOME/master.key` (mode 0600, §6.3). The file store is used when no keychain works (CI, a headless Linux) or when `FLOWFORGE_KEYSTORE=file`.
  
  Keychains can't list their entries, so the **names** (never values) are kept in `FLOWFORGE_HOME/keys.json`. Keys belong to one repo folder.
- **Two ways out.**
  - `flowforge run -- CMD …` starts the user's app with the keys added to its environment. It is a list, never a shell, and the exit code is passed through.
  - The redactor learns every saved value, so a value that reaches a log, a stored row or an answer is masked.
  
  No route, MCP tool or page returns a value, and no MCP tool takes one.
- **Four statuses**, for each env name the code reads that looks like a key (`is_secret_name`, D31):
  - **saved** in FlowForge, and read back to confirm it (Codex review: a key the keychain or file won't give back is **can't read**, offered to save again, because `flowforge run` couldn't pass it on). The agent's MCP server reads no value, so its "saved" means "on record";
  - **in .env**: only the name is read from the file, and each value is dropped as its line is read;
  - **missing**.
  
  The names and where they are read come from the scan as it is (`Dependency.env_names`, `ScanResult.env_names`), so `READER` doesn't change.
  
  A key belongs to a dependency when the scan sees it read on the dependency's own lines; else when its name names the service (`STRIPE_SECRET_KEY` → Stripe); else when its file has only one dependency.
- **On the map** (D33: no new page or header control):
  - a 🔑 badge on a block whose keys are missing (amber) or only in `.env` (grey);
  - a "Keys" part in the ⚠ chip;
  - the block's keys in the step panel.
  
  Each key offers the command to copy and a password box (`autocomplete=off`, emptied after it saves). Example mode shows the statuses but saves nothing (409).
  
  Saving or forgetting a key answers only to the dashboard's own address: a Host of `localhost`, `127.0.0.1`, `::1` or the `FLOWFORGE_HOST` chosen, and an Origin, if sent, of the same. Otherwise a web page could swap in its own key (its own Stripe account, say) through DNS rebinding. On a dashboard bound to `0.0.0.0` and opened from another machine, keys are added with the CLI. *(Changed by D37: the caller's real address must be this machine, and `FLOWFORGE_HOST` no longer counts.)*
- **For the agent:** a seventh read-only MCP tool, `get_keys`. It returns names, statuses, where each is read, which dependencies use it, and the command to ask the user to run. The MCP server, which the agent starts, never reads a value: not even to mask with.
- **No sign-in, no 2FA, no page that shows keys.** FlowForge is local and single-user (§6.5). A page that shows keys is a place keys leak (a screen share, a screenshot). The keychain is already locked by the user's login. To see a key, use the provider's dashboard.

**Why:** the user hands a key over once, and the agent wires it in by name. The key isn't left in a file the agent reads by habit.

**Honest limits** (the README says the same):
- An agent that can run commands as the user can still run `flowforge run -- printenv` or read the keychain. The promise is "never handed to the agent and not left lying in files", not "impossible to get".
- MCP servers that a coding tool starts get their env from that tool. FlowForge can't feed them without giving the agent the keys.
- A key already written in the code is reported (D31) but not moved yet: moving it edits code, so it needs a branch and the user's approval (Phase 10).
- On Linux, the Secret Service lets any program of the same user read the key without asking.

**Code:** `security/keystore.py`, `api/keys.py`, `cli.py` (`key`, `run`), `agent/server.py` (`get_keys`), the dashboard's `security/Keys.tsx`.

---

## D37. Issues and Keys pages, fixes you click, and a key view behind 2FA (Vishwa, 2026-10-24)

**Context.** v0.2.0 put keys and findings in a small popover whose fixes were commands to copy and edit. Vishwa: that isn't enough. People should do less, not more. Vishwa asked for:
- separate pages for issues and for keys;
- buttons that do the work;
- a way to see the keys behind two-factor authentication.

The rule from D36 stays: the coding agent never gets a value from FlowForge.

**Choice** (Vishwa picked each option):
- **Two pages.** **Issues** (`/issues`) and **Keys** (`/keys`) join the rail, with counts: Map · Issues · Keys · Checks · Connect agent. This supersedes D33's "no Security page". On the map, the ⚠ chip opens Issues and a 🔑 badge opens Keys; the popover goes.
- **Every issue has a button. FlowForge fixes what plain code can fix safely, and sends the rest to the agent ("Both").**
  - **Fix** handles a key written as a whole string literal in Python code, or in JavaScript or TypeScript that shows it runs on Node (`require`, `node:` or server imports, or `process.env` already; nothing of `window`, `document` or `import.meta.env`). Browser code goes to the agent (Codex review): a browser has no `process`, and a key bundled into a web page is public anyway. FlowForge works out the change without an LLM:
    - the value goes to the key store (D36), and `flowforge run` gives it to the app;
    - the literal becomes `os.environ["NAME"]` (adding `import os` when the file lacks it) or `process.env.NAME`.
    
    A key in `.mcp.json` goes to the agent (Codex review). The coding tool would read `${NAME}` from its own environment, and FlowForge must not fill that environment, because the agent runs in it.
    
    First a preview shows the diff with the key masked. Approve makes the change on a new branch, `flowforge/fix-…`, in a temporary `git worktree`, committed as the user. The branch the user works on is never touched, and the user merges when ready (§9.3).
    
    FlowForge refuses, and offers Send to agent instead, when the folder isn't a git repo or the file has uncommitted changes. The commit never holds the key. The fix still says to replace the key, because older commits do.
  - **Send to agent** covers what needs judgment: a key in `.mcp.json` or Dart, `http://` (the service may have no https), an unpinned server (which version?), a server given the whole disk (which folder?). The issue joins a queue that the agent reads with an eighth MCP tool, `get_fix_requests` (masked, like every answer). An issue leaves the queue when a re-scan no longer finds it. FlowForge doesn't start the agent: the page says to tell it "do the FlowForge fixes" (Phase 10 runs it).
  - Example mode previews every fix and applies none.
  - The Issues page reads the code each time it opens (plain code, nothing sent: D20), so a merged fix or an agent's edit shows at once. The map's badges still follow the saved map until a re-scan.
- **Keys page.**
  - Each key the code reads has a password box, always open, with no command to copy (§6.5: `autocomplete=off`, emptied after it saves).
  - A key that is only in `.env` has **Move into FlowForge**: the server reads that one value from the file and saves it.
  - A saved key has Replace and Remove.
  - Keys save in example mode too. They belong to the example's folder, so the demo works.
- **The key view: password + authenticator app.** It shows the values of the keys written in code, saved in FlowForge, and in `.env`. This supersedes D36's "no page that shows keys" and amends §6.5/§9.3: a secret is displayed only here.
  - **Set-up.** The user picks a password. FlowForge makes a TOTP secret (RFC 6238: SHA-1, 30 s, 6 digits) and shows it as a QR code for the phone. The secret is stored encrypted, with a key derived from the password by scrypt, in `FLOWFORGE_HOME/lock.json` (0600), next to a separate scrypt hash of the password. Without the password, nothing on disk can make a code. The first code must be typed before the lock is on.
  - **Open.** Password + current code (±1 step, no code used twice) opens a 5-minute session (an httpOnly, SameSite=Strict cookie). Five wrong tries lock the view for 15 minutes.
  - **View.** Values are masked until **Show**, which hides them again after 30 s. The view locks itself when the session ends.
  - **Reset.** `flowforge lock reset` asks for the password and a code. `--forget` drops the lock (the keys stay), writes it to `FLOWFORGE_HOME/lock-events.log`, and the dashboard shows "Key view was reset at …" until the next unlock.
  - **Guards.** Every route that saves a key, makes a fix, or touches the lock or a value answers only to this machine. The connection must come from loopback, and Host and Origin must name loopback too. Codex review: with `--host 0.0.0.0`, another machine could fake the headers, set up its own lock first and read every key; its real address can't be faked. The MCP server has no way to values.

**Why:** the user does one thing (paste, click Fix, click Approve) and FlowForge does the rest. The values stay where only the person with the password and the phone can open them.

**Honest limits:**
- An agent running commands as the user can still read the keychain or files directly, or `flowforge lock reset --forget` and set its own lock. The reset banner shows that it happened. The 2FA stops web pages, someone at the browser, and any caller without the phone.
- Fix covers keys in Python/JS/TS code. The rest goes to the agent.
- "Send to agent" waits for the user to tell the agent.

**Code:** `security/finders.py` (`key_span`), `security/fixes.py`, `security/lock.py`, `api/issues.py`, `api/keys.py`, `agent/server.py` (`get_fix_requests`), the dashboard's `security/IssuesPage.tsx` and `KeysPage.tsx`.

---

## D38. Lanes on the map, keys your agent asks for, and the Vault (Vishwa, 2026-10-24)

**Context.** Vishwa's look at the v0.3.0 build had three points:
- **The map was cluttered.** In Boxed, each kind's box wrapped its blocks wherever they sat in the one column. Wikipedia (an API reached through `fetch`) sat up top, so the APIs box covered every other box.
- **Keys should follow the agent's work.** The agent adds a dependency and asks for its key. The user clicks the new block, pastes the key, and the agent carries on.
- **Key values don't belong on the Keys page.** The set-up there felt small and informal.

**Choice** (Vishwa picked each):
- **Lanes (amends D26).** In Boxed, a dependency map is laid out by code: the app's and the coding tools' start blocks on the left, then one lane per kind, side by side: MCP servers · LLMs · APIs · Local programs, each sorted by name. A block reached through a server sits in its own kind's lane, and its line crosses over. Like the time columns on a flow, this layout is tidied, never saved.
- **A block whose key is missing** gets a coral outline and "key missing". Its panel's first button, **Add the key**, opens the Keys page with that key's box focused (`/keys?key=NAME`).
- **The agent asks (amends D29).** Two MCP tools, neither of which ever holds a value:
  - `request_key(name, why)` records a request: the env name, one line of why, the folder. It is the one tool that writes anything, and it writes only that request.
  - `wait_for_keys(names, seconds)` returns as soon as each key is saved, or when the time is up (at most 110 s; call again to keep waiting). It reads the store's list of names, never a value.
  
  The Keys page shows requests first ("Your agent is waiting for …"). A request counts in the rail and clears once its key is saved. When a request arrives, the map shows "Your agent asked for a key · Review", which opens the usual re-scan diff, so the user sees what the agent added before it lands on the map (D17).
- **The Keys page** only adds keys. The order is the agent's requests, then missing, then in `.env`, then saved (folded). The `flowforge run` line is one short row with Copy.
- **The Vault (amends D37).** A rail page of its own, `/vault`, and the only place values show.
  - **Locked:** two screens, one at a time. First the password: `POST /lock/password` counts tries and gives a 2-minute half-ticket in an httpOnly cookie. Then the code: `POST /lock/code` needs that ticket. Then 5 minutes open. Five wrong tries, across both steps, lock it for 15 minutes.
  - **Set-up:** a full-page wizard in three steps (password, a large QR with the key to type if it can't be scanned, the first code).
  - **Open:** every key, from the code, the store and `.env`, with its health and details. Health is healthy, in code, in `.env`, can't read, unused (saved but no code reads it), or saved 90+ days ago. Details are where it lives (keychain, encrypted file, `file:line`, `.env`), the dependency it serves, when it was saved, and live or test (worked out on the server from the key's prefix; only the word comes back).
  - **Actions:** Show (30 s, D37), Fix (to Issues), Move in, Remove. A countdown and Lock now.

**Why:** the map should read at a glance. The user does one thing per key (paste) while the agent waits. Seeing values is a separate, deliberate act behind two steps.

**Code:** `frontend/src/flowmap/themes.ts` (`kindLanes`), `agent/server.py` (`request_key`, `wait_for_keys`), `api/keys.py`, `api/lock.py` (`/lock/password`, `/lock/code`, `/vault/keys`), `security/lock.py`, the dashboard's `security/VaultPage.tsx`.

---

## D39. Projects: a home with every project, and a picker in the rail (Vishwa, 2026-10-24)

**Context.** FlowForge was one process for one folder: one database, one repo setting, one map. A different folder needed `--replace`, which wiped the map. Vishwa wants:
- a main page listing every project;
- opening one gives its own workspace (map, Issues, Keys, Vault, Checks, Connect agent);
- switching between projects keeps each as it was left;
- closing one never deletes it.

This is step ① of Vishwa's order (① projects, ② settings + first run, ③ CLI, ④ the Tauri desktop app).

**Choice** (Vishwa picked a picker in the rail over a tab bar):
- **One database per project**, at `FLOWFORGE_HOME/projects/<id>.db`. `projects.json` lists each project: id, name, folder, database, when it was added and last opened. The database that existed before (with its repo setting) becomes the first project where it lies, and nothing moves. Example data is a built-in, read-only project.
- **Every request names its project.**
  - A middleware reads a `/p/<id>/` prefix, strips it and sets the project in a context variable.
  - `app_state()` returns that project's state, built on first use (today's start-up, per project) and kept after.
  - No route changes. A request with no prefix means the default project (the last one opened), so the MCP server, old links and scripts keep working.
- **Shared across projects:** one redactor (it learns every project's saved keys, D36), the Vault's one lock per user (D37), and the keychain (keys already belong to a folder).
- **The dashboard:**
  - `/` is the home: a card per project with its dependencies, issues, missing keys and when it was last opened, plus **+ New project** and the example's card.
  - A project's pages live under `/p/<id>/…`.
  - The top of the rail is the **project picker**. It lists the projects you have open, the current one first; each comes back as it was left (its page, map view, open block and style). **×** closes a project from that list and never deletes it. The picker also has **All projects** (the home) and **+ New project**.
- **New project:** pick the folder; FlowForge scans it (plain code, D20) and shows its map. There's no agent step.
- **The agent is paired once, not per project** (Vishwa's choice). `flowforge mcp` with no `--repo` serves every project:
  - each tool takes an optional `project` (an id or a name);
  - without one, it answers about the project whose folder holds the agent's working directory, else the last one opened;
  - a new read-only tool, `list_projects`, lists every project with its status.
  
  `flowforge mcp --repo PATH` still works as before. The screen that pairs the agent belongs to step ② (Settings + first run).
- Removing a project from FlowForge deletes only FlowForge's copy of its map and checks, after you confirm. It never touches the folder. Removing the default project hands over to the project opened most recently; with none left, FlowForge offers to scan a folder (Codex review).
- **Amends D21:** a different folder is a new project, so `--replace` and the one-folder rule go. `flowforge --repo PATH` opens that folder's project, adding it if new.

**Why:** most people work on more than one app. Each one deserves its own map, issues and keys, and switching shouldn't cost anything.

**Code:** `backend/flowforge/projects.py`, `state.py` (`app_state`), `main.py` (the middleware), `api/projects.py`, the dashboard's `projects/ProjectsPage.tsx`, `ProjectPicker.tsx`, `api/client.ts`.

---

## D40. Settings, and a welcome the first time (Vishwa, 2026-10-24)

**Context.** This is step ② of Vishwa's order. A first-time user landed on "No projects yet" and was never shown the agent or the Vault. Settings were scattered:
- the theme sat in the rail;
- the agent was paired per project on Connect agent;
- the MCP servers you said yes to lived under Checks.

D39 left pairing the agent once to this step.

**Choice** (Vishwa picked the welcome, the four cards and the gear):
- **A welcome, once.** It is full-screen and shows on a launch with no projects, until it is finished or skipped. It has three steps, and each can be skipped:
  1. **your app:** a folder to map, or the example;
  2. **your agent:** one line for Claude Code, Codex or Antigravity that serves every project (`flowforge mcp` with no folder, D39), then "Waiting for your agent…" until its first call;
  3. **your keys:** the Vault's lock, a password then an authenticator code (D37), optional.
  
  Finishing or skipping sets `welcome_done` in `FLOWFORGE_HOME/settings.json`, which never holds a secret.
- **Settings** (`/settings`, for every project) sits behind a ⚙ at the bottom of the rail. The theme moves out of the rail into it. Four cards:
  - **Your agent:** connected or not (the newest call in any project) and the pair-once line per agent.
  - **Look:** the theme, and the map style a new map opens in. Each map's Style ▾ stays.
  - **Keys & Vault:** whether the lock is set, and where keys are kept (keychain or encrypted file), with a link to the Vault. No value and no way to change the lock here.
  - **Data & checks:** where FlowForge keeps its data and how big each project's database is, the MCP servers each project said yes to (take the yeses back), clearing a project's check history, the version, and **Check for updates**.
- **No login for Settings** (Vishwa asked whether one is needed). Settings shows nothing secret and can't open the key view or change the lock: those stay behind the Vault's password and code. Every change in Settings answers only to the dashboard on this machine (`from_this_machine`, D36).
- **The update check** is the only request Settings makes to the internet: one GET to pypi.org for `flowforge-map`'s latest version, and only when you press the button. Nothing is sent but that request.

**Why:** the first five minutes decide whether someone stays. The welcome gets them to a map, a paired agent and locked keys. Settings puts what applies to every project in one place.

**Code:** `backend/flowforge/settings.py`, `api/settings.py`, `api/agent.py` (pair once), the dashboard's `settings/SettingsPage.tsx`, `welcome/Welcome.tsx`, `components/Shell.tsx`.

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
