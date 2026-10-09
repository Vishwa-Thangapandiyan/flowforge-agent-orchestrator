# CLAUDE.md

Guidance for Claude Code when working in this repository. Read this whole file at the start of every session. Then read the section of `DECISIONS.md` that matches the code you are about to touch.

---

## 0. Status (update this block at the end of every phase)

| | |
|---|---|
| Branch rules | `DAA` = frozen course project. **Never commit to it, never merge into it.** `main` = the product. |
| Current phase | **Phase 3: flow map V1 (D17, D18), implemented on `feat/phase-1-connectors`, uncommitted, awaiting Vishwa's review (Vishwa commits).** Phases 1 and 2 are committed there. Next: Phase 4. Roadmap (renumbered in D17): 4 = security (vault, redact/verify/scan/restore), 5 = real Planner + approval gates, 6 = swap + coding connector, 7 = server + workers, 8 = visual builder |
| Direction | The Planner (a background LLM; its engine is never shown or user-selectable) reads the repo, runs the app in test mode and draws the app's AI flow as the home-page map. Only apps the code calls go on it. The user reads it, edits through overrides that never touch code, and re-checks to get a diff (section 1, D17). Workflow JSON and the API stay as the Advanced path |
| Done | Scheduler core, five policies, caches, SSE run stream, plain-HTML status page. Phase 1: D10 connectors (provider-agnostic `LLMNode`: openai_compatible + anthropic; per-connector buckets, cache namespaces, fallback), D12 MCP (tool discovery, schema-checked calls, non-text blocks, artifacts), D13 `local` step, connector registry + presets + `connectors.json`, HTTP connectors, ruff, CI (Linux + Windows), CONTRIBUTING. Phase 2 (D15, D16): dashboard (Vite + React + TS), persisted runs and events, minimal redaction (`security/logfilter.py`), connector create/edit/delete + logos, tool health, savings, example-data mode, `flowforge` command. Phase 3 (D17, D18): `flowmap/` (Flow JSON models, validation, code-inserted policy gates, critical path, overrides merge, version diff, `Planner` protocol + `FixturePlanner`), storage tables `flow_versions`/`flow_overrides`/`flow_positions`, `/flow*` and `/catalog` routes, 56-app catalog with mock test runs; dashboard: icon rail, flow map at `/` (React Flow + dagre, saved positions, search, legend, minimap, step panel with evidence and edits, test-run replay that holds at the gate), `/map/how`, `/map/recheck`, catalog at `/connectors`, money/time + app health on Runs, Geist fonts; Overview and HubMap removed; `Storage` calls serialised by a lock. 314 backend (+1 skipped) + 54 dashboard tests pass offline |
| Not started | The real Planner (repo reading, test-mode run, tracing), connector `describe()` (partly met by MCP `list_tools()`), vault, full redact/verify/scan/restore, Security page, testing llm/http connectors, gate steps in scheduled runs (D11), swap flow, coding connector, distributed workers |
| Next decision needed | Section 12 (open questions; 12.1 and 12.5 are settled by D15 and `docs/design/`). Whether to code-split the dashboard bundle (709 kB, Vite warns over 500 kB). Whether to delete `frontend/classic.html`. Whether a user-chosen background engine for the Planner comes back later (D17 hides it for now). Ask Vishwa, don't guess. |

---

## 1. What we are building

**FlowForge is the scheduler layer for agent workflows, plus a dashboard to connect, watch and control them.**

You connect apps (LLMs, MCP servers, HTTP APIs, local commands) to one project. FlowForge runs them as a DAG: it orders steps, runs independent ones together under rate limits, caches repeat calls, holds the secrets, and pauses risky steps for a human to approve.

Positioning: not LangGraph (code-first agent graphs), not Airflow (data pipelines), not n8n (no scheduler, no cost model). The pitch is *"it knows which chain of steps is the bottleneck and schedules around it, and it never lets a key reach an LLM."*

- **Audience:** developers first. Non-technical users later (a visual builder is Phase 8, not now).
- **Open source.** MIT licence is already in the repo. Keep the README and CONTRIBUTING friendly to strangers.
- **No fixed deadline.** Prefer correct and tested over fast.
- **Hard constraint: zero cost by default.** No paid APIs or services in the default install, tests or CI. Free tiers (NVIDIA NIM) and local models (Ollama) only. Optional paid providers (Claude, Gemini, Stripe, Razorpay) work if the user brings their own key, and are never needed to run tests.
- **Local first.** SQLite, files on disk, one process. No cloud account, no Docker requirement, no Redis until Phase 7.

### The core user experience (D14, revised by D17)
FlowForge is an **LLMOps tool for apps that already use AI**, not an app builder. **The Planner draws the map; the user reads it and edits only when needed.**

1. **Connect.** The user picks apps from the catalog (Razorpay, Gemini, an MCP server, a script…). Each app has a mock "Test run".
2. **Map.** The Planner reads the repo and runs the app in test mode. It then draws the app's AI flow:
   - start/end, app calls, plain code;
   - decisions, run-together/wait-for-all, retries and fallbacks.

   Plain code gathers the facts first (routes, outside calls, env var *names*, never values) and redacts them; only then does the Planner see them. **Only apps the code already calls go on the map.**
3. **Validate.** Code checks the map: cycles, missing connectors, unknown tools, evidence.
   - A block with no evidence is dropped or marked *unconfirmed*.
   - Code puts a gate before every payment, message, code change and other side effect. No edit can remove it.
4. **Look and adjust.** The map is a canvas: pan, zoom, drag, click a block for its evidence. Edits (swap an app, rename, hide, add a step) are overrides on the Planner's version and **never change the user's code**.
5. **Re-check.** The Planner looks again and shows a diff. The user picks what to take; the old version stays.
6. **Run and watch.** In V1 a test run replays a traced order on the map. Scheduled runs of the flow, with gates, come with the real Planner (Phase 5).

**The LLM decides WHAT. The scheduler decides WHEN. The LLM proposes; the user approves.** Validation catches structural errors, not wrong ideas, which is why the gates stay. Hand-written workflow JSON and the existing API remain the **Advanced** path for developers and CI.

### UI principle (applies to every screen)
The dashboard must be **scannable**: colour-coded, short labels, diagrams before paragraphs, one idea per card. If a screen needs a paragraph to explain itself, redesign the screen. Everything the user reads should be at most one short sentence per element.

---

## 2. Design reference (the spec for the UI)

**The current spec is `docs/design/flow-map-artboards/` (D17, D18; approved 2026-10-09).** It has five Claude Design artboards:
- the flow map (home);
- how the Planner draws the map;
- the re-check diff;
- the connector catalog;
- building blocks + Flow JSON + type.

It replaces View 1 (hub map) and View 7 (plan-review list) below, and the fonts (now Geist + Geist Mono). The older pages stay the reference for the connector zoom, add-an-app, run detail, swap and security views. Change the look only through new artboards that Vishwa approves.

The original UI was designed as three interactive pages. They are the visual spec. **Do not invent a new look.**

Before starting Phase 2, make sure these exist in the repo (ask Vishwa to add them if missing, they were published as claude.ai artifacts):

```
docs/design/system-map.html     <- MOST IMPORTANT. 6 views: hub map, zoom panel, swap, run sequence, add-a-connector, security
docs/design/plan.html           <- roadmap + the "dashboard of dashboards" model + example run
docs/design/swap-flow.html      <- the swap-an-app flow + redact/edit/restore walkthrough
```

Read `system-map.html` fully before writing any frontend code. Take from it, verbatim where possible:
- the `:root` colour tokens (light + dark), fonts, spacing, radii. Copy them into `frontend/src/styles/tokens.css`;
- the step-type colours: `http`, `app` (plain script, no LLM), `llm`, `gate` (human approval, dashed), `mcp`, `output`;
- the brand-tile classes (`brand-razor`, `brand-stripe`, `brand-gem`, `brand-nim`, `brand-claude`, `brand-sirius`);
- the JS data shape of `APPS` (name, role, mono, brand, status, conn, form, tasks, log). That object is the shape of what the API should return for one connector's zoom panel.

The six designed views, plus the one still to design, and what they become:

| # | View in the map | Becomes | Route |
|---|---|---|---|
| 1 | Hub map: project in the middle, one box per connected app/LLM/tool, green dot = connected | Home screen | `/` |
| 2 | Zoom into one box: Connection, The form you filled in, Tasks inside this box, Recent activity | Side panel / page for one connector | `/connectors/:id` |
| 3 | Swap: a *slot* (e.g. Payments) holds Razorpay or Stripe; everything else is unchanged | Swap flow | `/connectors/:id/swap` |
| 4 | Sequence: webhook → verify signature → fetch order → redact → LLM → update order → stream to dashboard | Run detail / log | `/runs/:id` |
| 5 | Add your own: pick type, name, connect, style (colour + logo), live preview, JSON that gets saved | "Add app" screen | `/connectors/new` |
| 6 | Security: redact demo, seven guards, six privacy rules, honest limits | Security tab | `/security` |
| 7 | *Not designed yet.* Plan review: "Here's what will happen", one confirmation | Plan review before every planned run | `/plans/:id` |

**Not designed yet: View 7, Plan review** (Phase 5, D14). It's the "Here's what will happen" list from section 1, not a graph:
- the steps in order, with steps that run together grouped on one row;
- the estimated total time (from the critical path);
- for each step, the connector it uses and the secrets it touches (names only);
- a gate badge on every step that needs approval, plus what was dropped and why (evidence not found);
- one primary button, **"Looks good, run it"**, and a way to ask for a new plan.

Before building it, ask Vishwa to add it to `system-map.html` as **View 7** in the same style, so the UI isn't invented on the fly. Graph views exist only under **Advanced** and are not part of View 7.

Logos (D15): preset brands use the **CC0 SVG marks from the `simple-icons` package**, inside a brand-colour tile, only to identify the integration (nominative use; never altered, never implying endorsement). A brand that isn't in the package, and Sirius, gets a two-letter monogram tile. Custom apps use letters + colour or the user's uploaded image (rules in section 6.5). Never hand-draw a company logo or copy one from a brand site.

---

## 3. Architecture (target)

**Hub and spoke. Nothing talks to anything else directly. Every call goes through FlowForge core.**

```
                         ┌─────────────── dashboard (browser) ───────────────┐
                         │  hub map · zoom panel · swap · run log · add app  │
                         └──────────────▲──────────────────────────┬─────────┘
                                 SSE events                  REST (write-only secrets)
┌──────────── FlowForge core (FastAPI, one process) ───────────────┴─────────┐
│  scheduler (Kahn, critical path, HLFET, rate limits)   ← already built     │
│  caches (in-run single-flight + persistent SQLite)     ← already built     │
│  connector registry  → builds Node instances           ← Phase 1/3         │
│  vault + redaction + guards                            ← Phase 4           │
│  approval gates + planner (plan → DAG → plan review)   ← Phase 5           │
│  storage: runs, durations, cache, connectors, boards   ← SQLite            │
└──▲───────────▲───────────────▲──────────────────▲─────────────────────────┘
   │ llm       │ mcp           │ http             │ local command
 NIM/Gemini/   any MCP server  Razorpay/Stripe/   Sirius, scripts,
 Claude/Ollama (tools auto-    any REST API       models on your machine
               discovered)
```

Key idea: a **connector** is configuration (who, how to connect, how it looks, which secret). A **Node** is the runtime code that executes one call. The existing `Node` classes stay; connectors build and configure them. Do not rewrite the scheduler to know about connectors. The executor keeps seeing `node.run(params)`.

---

## 4. The existing core (keep it working)

This is the DAA code on `main`. It is correct, tested and benchmarked. **Extend it, don't rewrite it.**

### Commands
Uses `uv`, Python >= 3.12. No linter configured yet (add `ruff` in Phase 1, see 9.1).

```bash
uv sync                                          # deps + dev tools into .venv
uv run pytest                                    # full suite, offline, no API key
uv run pytest backend/tests/test_executor.py     # one file
uv run pytest backend/tests/test_graph.py::test_topological_order_respects_edges
uv run uvicorn flowforge.main:app --reload       # API + status page on :8000
uv run python benchmarks/run_benchmark.py sim --graphs 500 --k 4   # offline
uv run python benchmarks/run_benchmark.py real   # needs NVIDIA_API_KEY in .env
```

`pytest-asyncio` is in `asyncio_mode = "auto"`. **Tests must never touch the network.** Use `mock` steps or stub clients the way `test_llm_node.py` / `test_mcp_node.py` do. API tests point `FLOWFORGE_DB` at a tmp path. `*_properties.py` are hypothesis tests that check graph, critical-path and executor invariants against brute force on random DAGs.

### Layout (package root `backend/flowforge`)
1. `schema.py`: Pydantic `Workflow` / `Step`. `extra="forbid"`. Validation runs before execution and rejects the whole workflow (duplicate ids, unknown/self `depends_on`, templates referencing steps outside `depends_on`). `StepType = Literal["llm","mcp","http","mock"]`.
2. `scheduler/graph.py`: Kahn's toposort + BFS levels. On a cycle it reports the actual loop (`a → b → c → a`).
3. `scheduler/durations.py`: weights from EWMA history in SQLite (alpha 0.3, key `(workflow_id, step_id)`) → `estimated_ms` → per-type default.
4. `scheduler/critical_path.py`: longest-path DP; reverse topo order gives **bottom levels** = HLFET priorities; lower bound `max(CP, work/k)`.
5. `scheduler/executor.py`: `run_workflow()`. One dispatcher loop makes every decision; each running step is an asyncio task. A ready step starts only when a global slot **and** its type slot are free. Then: rate-limit token → resolve templates → `node.run` under `asyncio.wait_for`. Transient errors retry with full-jitter backoff (or `Retry-After`), each attempt takes a fresh token. A failure marks all descendants `skipped`; independent branches continue. `policy` picks one of five strategies via the heap key: `sequential`, `levels`, `greedy`, `fifo`, `critical_path`. **Any scheduling change must keep all five working.** Events go out through `on_event` and the API streams them.
6. `scheduler/cache.py`: in-run single-flight (identical calls share one `Future`; a waiter takes no slot) + persistent SQLite cache only where safe: `llm` at temperature 0, `http` GET, `mcp` only if the step opts in. Key = sha256(type + canonical JSON of the *resolved* params). `step.cache` overrides the default.
7. `templating.py`: `{{steps.<id>.output.<path>}}`; a string that is exactly one template yields the raw value, otherwise `str()` interpolation.
8. `nodes/`: subclass `Node` (`base.py`): `async run(params)`, `cacheable_across_runs(params)`, `rate_limit_key` (class attr), `aclose()`. Raise `TransientNodeError` for 429/5xx/timeout/connection (retried), `NodeError` for permanent failures.
9. `main.py`: FastAPI. Lifespan builds node instances, rate-limit buckets, `Storage`. `POST /runs` starts a background run; `GET /runs/{id}/events` replays all events over SSE. **Runs are currently kept in memory.** Serves `frontend/index.html` (single plain HTML page, no build step) and `backend/workflows/*.json`.
10. `storage.py`: SQLite (`flowforge.db` or `FLOWFORGE_DB`): run history, duration history, persistent cache.

### Known limits of the current nodes
Fixed in Phase 1: `LLMNode` is no longer NIM-only (D10); `MCPNode` has tool discovery, per-server secret env refs and non-text results (D12). Still open:
- `kind` hints exist only on MCP non-text blocks and `local` output; the dashboard's output viewer picks a view from the output's shape instead (table / text / image / JSON).
- `usage.credits` is always 0: no provider reports credits yet, and FlowForge does not invent prices.
- Bare `LLMNode()` (tests and the real benchmark track) keeps the V1 output without `usage.credits`; connector-built nodes include it.
- Secrets resolve from `env:` refs only; `vault:` refs are refused until Phase 4. Since Phase 2 a minimal redactor (D16) masks known key shapes and configured key values in stored runs, events, cache rows, API results and logs; it is pattern-based, not the full Phase 4 pipeline.
- Connectors can be added and edited from the dashboard (D16); those from `connectors.json` are read-only there. "Test connection" works for MCP and local apps only; llm/http arrive in Phase 4.
- The default `mcp` node is still the V1 node (it accepts `params.server`); the `fetch` connector is separate, so `mcp` and `fetch` may each spawn their own fetch server.
- On Windows, killing a timed-out `local` process does not kill its children.
- Runs that were running when the server stopped are marked `interrupted`; they are not resumed.
- Live run has Stop but no Pause (a pause would change the scheduler).
- The flow map runs on example data only: the one Planner is `FixturePlanner` (the "Baby-care shop" app), and outside example mode the map shows an empty state until Phase 5. Its Test run replays a recorded trace and makes no calls; catalog test runs are canned mocks.
- Map gates are inserted by code (D17), but scheduled runs have no gate step yet (D11, Phase 5). A GET to a payment API isn't gated; any other method is, and an HTTP block with no method counts as a write (D17).
- `Storage` shares one SQLite connection across the threadpool, so every public method takes one `RLock` (a race existed since sync connector routes; `test_storage_threads.py`). Fine for one local user; revisit with Postgres in Phase 7.
- The dashboard bundle is about 709 kB (React Flow + dagre); Vite warns over 500 kB. No code splitting yet.
- Timing-sensitive tests: tests assert scheduling decisions, not wall-clock windows. Exception: `actual_critical_path` in `test_diamond_meets_lower_bound` still depends on measured durations; it held in 500 stress runs.

### Rules that already exist and must not break
- `DECISIONS.md` is the spec: D1–D9 (V1), D10 connectors, D11 approval gates (reserved, written with Phase 5), D12 MCP connectors, D13 local command step, D14 plan from connectors, D15 frontend stack, D16 run history + redaction + example mode + editable connectors, D17 the flow map (also renumbers the roadmap), D18 frontend additions (Geist, React Flow, dagre). Cited in code as `(D7)` etc. Keep code and doc in agreement. **New decisions get the next free number (D19, …) in the same format**, written *before* the code.
- Say "concurrent on one event loop (I/O-bound)", never "parallel on CPUs" (D4).
- Benchmarks must keep running unchanged (`benchmarks/`). Don't change the five policies' behaviour to make a new feature easier.

---

## 5. Roadmap and acceptance criteria

Work in this order. Each phase = one branch `feat/phase-N-<name>`, one PR into `main`, tests green, `DECISIONS.md` updated, status block (section 0) updated. **Start every phase in plan mode** and show Vishwa the plan before editing.

### Phase 1: Any LLM, any MCP server  *(done, on `feat/phase-1-connectors`)*
Goal: stop being NIM-only.

1. **Provider-agnostic `LLMNode`.**
   - Config object `LLMConnectorConfig(provider, base_url, model, api_key_ref, rpm, temperature_default)`.
   - `provider` ∈ `openai_compatible` (covers NIM, Gemini's OpenAI-compatible endpoint, Ollama, vLLM, OpenRouter), `anthropic` (native SDK, add `anthropic` dependency).
   - Each configured LLM connector owns its **own** rate-limit bucket (`rate_limit_key = connector id`, not the literal `"nim"`). Keep `NIM_RPM` env behaviour for the default connector so existing tests and benchmarks pass.
   - Step selects a connector with a new optional field `connector: str | None` on `Step` (default = the type's default connector, so every existing workflow JSON stays valid).
   - Error mapping stays the same: 429/5xx/timeout/connection → `TransientNodeError` with `Retry-After`; everything else → `NodeError`. Messages name the provider, not "NIM".
   - Output keeps `{"text","model","usage":{"prompt_tokens","completion_tokens"}}` and adds `usage.credits` (default 0).
   - Fallback: `connector.fallback = "<other connector id>"`, tried on permanent `TransientNodeError` exhaustion only. Record which one answered in the event.
2. **MCP: any server, discovered tools.**
   - `MCPConnectorConfig(command, args, env_refs)`; env values that are secrets are vault refs, resolved only at process spawn.
   - `list_tools()` on the connection returns names + JSON schemas. Expose `GET /connectors/{id}/tools` (Phase 4 wires the UI).
   - Validate `params.tool` and `params.arguments` against the discovered schema **before** a run when the server is reachable (warn, don't fail, when it is not).
   - Handle non-text result blocks: image → `{"kind":"image","mime","data_b64" | "path"}`, audio/video the same, resource links kept as URLs. Large binary payloads are written to `~/.flowforge/artifacts/<run_id>/` and referenced by path, never stuffed into the run JSON.
3. **Local command connector** (`type: "local"`, new `StepType`): runs a configured command with args from params, captures stdout/stderr/exit code. No shell (`shlex.split`, `subprocess` list form), working directory restricted to a configured folder, timeout from the step. This is how Sirius and Ollama-side scripts plug in.
4. **Connector registry (config only, no UI yet).** `backend/flowforge/connectors/` with `models.py` (Pydantic, section 7.1), `registry.py` (load/save in SQLite table `connectors`), `presets.py` (section 7.3). Lifespan builds nodes from the registry instead of hard-coding the four.
5. **Tooling:** add `ruff` (lint + format) to the dev group, a `.github/workflows/ci.yml` that runs `uv sync && uv run ruff check && uv run pytest` on push/PR (no secrets, no network), `CONTRIBUTING.md`, and a README "Quickstart in 3 commands".
6. **Forward compatibility with the Planner (D14).** Every connector exposes `describe()`: a capability summary the Planner reads in Phase 5. It returns the connector's id, type and role, plus what it can do with input schemas:
   - MCP: tools and their JSON schemas;
   - HTTP: endpoints (method, path, parameters) when OpenAPI or docs are given;
   - LLM: provider and model;
   - local: command and the arguments it accepts.

   It never includes secret values, only `secret_ref` names. It must be cheap and side-effect free; MCP may cache its discovery.

   **Status on `feat/phase-1-connectors`: partly satisfied, not yet met.**
   - `MCPNode.list_tools()` already returns each tool's name, description and JSON input schema, and `GET /connectors/{id}/tools` exposes it.
   - There is no uniform `describe()` on connectors or nodes.
   - HTTP connectors have no endpoint or OpenAPI summary.
   - LLM and local connectors expose nothing beyond their config.

   Add a thin `describe()` (backed by `list_tools()` for MCP, and by config for the others; HTTP OpenAPI import can wait for Phase 5) either before the Phase 1 PR or as Phase 5's first task.

**Acceptance:** all existing tests pass unchanged; new tests cover each provider with stubbed clients; an MCP test using an in-process fake server proves discovery + schema validation; a workflow that uses two different LLM connectors with different rpm shows two separate buckets in a test; benchmarks still run.

### Phase 2: Dashboard v1  (frontend + persistence)
Goal: the hub map + live run + tool health + money and time, read-only first.

1. Persist runs: replace the in-memory `s.runs` with SQLite-backed run history (keep the in-memory live buffer for SSE). `GET /runs` (list, newest first), `GET /runs/{id}`.
2. Frontend scaffold (frontend-stack decision in section 12, next free D-number): `frontend/` with tokens from `docs/design/system-map.html`.
3. **Home `/`**: hub map (View 1) rendered from `GET /connectors`: one box per connector (brand tile, name, role, status dot), project box in the middle, lines through the hub. Click → `/connectors/:id`.
4. **Four panels** (from `plan.html`): *Live run* (the run's steps as an ordered progress list, with steps that run together on one row; each step lights up over SSE, the critical path is marked, and clicking a step shows its output; a graph view only under Advanced), *Tool health* (one card per connector: up/down, last success, rate-limit left), *Money and time* (calls made vs skipped by cache, tokens, credits, time saved = sum of step times minus makespan), *Controls* (run, retry, run history).
5. Keep the old `frontend/index.html` working until the new UI reaches parity, then delete it in its own commit.

**Acceptance:** with only mock steps and no keys, `uv run flowforge` (add a console script) opens a dashboard that shows a project, runs `diamond_mock.json`, and updates live. Component tests for the map and the step-state colours.

### Phase 3: Flow map V1  *(D17, D18; artboards in `docs/design/flow-map-artboards/`; implemented on `feat/phase-1-connectors`, in review)*
Goal: the approved artboards for real, end to end on example data. The Planner is a swappable interface with one implementation, the example-mode fixture. Real repo analysis waits for Phase 4's redaction.

1. **Backend `flowmap/`:**
   - the Flow JSON models (block and line kinds in D17);
   - validation: cycles except retry self-loops, connectors exist, evidence or `unconfirmed`, **policy gates inserted by code before side effects**;
   - the fixture Planner, version diff and the merge of the Planner's version with the user's overrides.
2. **Storage and API:**
   - storage tables: `flow_versions`, `flow_overrides`, `flow_positions`;
   - routes: `GET /flow` (`layer=mine|planner`), positions, overrides (an override can never hide or remove a gate), trace, analysis, re-check, then accept or discard a version;
   - older versions stay listed.
3. **Catalog:**
   - the 56-app catalog lives in `connectors/presets.py`;
   - `GET /catalog` reports each app as `on_map`, `connected` or `none`;
   - `POST /catalog/{id}/test` is mock and offline.
4. **Frontend:**
   - the compact rail;
   - the flow map at `/`: React Flow, dagre layout, saved positions, search, legend, minimap, the step panel with evidence and edits, and a test-run replay that pauses at gates;
   - `/map/how`, `/map/recheck`, and the catalog at `/connectors`;
   - Geist fonts;
   - Overview and HubMap are removed.

**Acceptance:**
- In example mode the map renders, a dragged step stays put after a reload, and the replay pauses at the gate until Approve.
- A connector swap shows as "Yours", and "Planner's map" hides it.
- Re-check → diff → save gives v2, and v1 is still listed.
- The catalog filters work and its test run works offline.
- A side-effecting block without a gate in the Planner's output gets one from code.
- Outside example mode the map shows an empty state.
- No test needs a network or a key; the scheduler and benchmarks are untouched.

### Phase 4: Connectors, forms, secrets, security
Goal: View 2 + View 5 + View 6 for real. **This is the security-critical phase; section 6 is binding.**

1. Vault + redaction + guards (section 6), fully tested before any UI uses them.
2. `POST/PUT/DELETE /connectors`, `PUT /connectors/{id}/secret` (write-only), `POST /connectors/{id}/test` (one harmless call per type), `GET /connectors/{id}/tools`.
3. **Add-app screen** (View 5): type cards → name → connect fields (change with type) → style (colour swatches + custom colour, logo = letters | upload | none) → live preview of the map node and side-panel header → "Test connection" turns the dot green.
4. **Zoom panel** (View 2): Connection (secrets show `configured ••••••` only), The form you filled in, Tasks inside this box, Recent activity.
5. Presets (section 7.3), brand tiles, logo upload rules (6.5).
6. **Security tab** (View 6): the redact demo against fake keys running on the real redaction module through `POST /security/redact-demo` (accepts text, returns only redacted text and masked mapping), the seven guards, six privacy rules, honest limits.

### Phase 5: Approval gates + auto-plan
> **Revised by D17:**
> - The plan *is* the flow map (Phase 3), so View 7's list is gone.
> - The Planner's engine is hidden and is not picked in settings.
> - "Run the app in test mode and trace its calls" belongs to this phase.
> - The Planner fills the same Flow JSON and trace the Phase 3 fixture produces.
> - Scheduled runs of a flow need conditional branches and gates in the executor (D11).

Goal: the core flow in section 1. The user connects apps; FlowForge plans, the user reviews one list, confirms once, and the scheduler runs it. **Gates ship in the same phase as the Planner, because a plan can include side effects.** The LLM proposes; a human approves; nothing is applied automatically. Contract: D14 (write it before code, together with D11).

1. **Gate step** (`type: "gate"`, D11, notes in section 8). Pauses a run until `POST /runs/{id}/steps/{step}/approve|reject`.
   - Payments, code changes and every side-effecting step are **always** gated. No setting turns this off.
   - Code decides whether a step is side-effecting, not the LLM:
     - non-GET HTTP;
     - payment connectors;
     - MCP tools not annotated read-only;
     - `local` steps;
     - anything that writes code.
2. **`describe()` on every connector** (if it didn't land in Phase 1): the capability summary the Planner reads.
3. **Fact sheet**, built by plain code with no LLM:
   - each connector's `describe()` output, including MCP tool schemas and HTTP OpenAPI/docs if given;
   - for a linked repo: the file tree, dependency files, route and webhook handlers with `file:line`, and env var *names* (never values).

   Everything passes through `redact` (6.4) before any prompt, and the fact sheet is hashed so the plan can cite which facts it used.
4. **Planner call.** Any LLM connector, chosen in settings as the "Planner model". Temperature 0, cached like other LLM calls, and counted in "Money and time". The output is a typed plan: tasks with connector, tool or endpoint, params, `depends_on` and `evidence`. The exact contract is in D14.
5. **Evidence rule.** Each task's `evidence` must name a tool, route or `file:line` that exists in the fact sheet. **A task whose evidence doesn't exist is dropped**, along with tasks that depend on it, and the plan review says what was dropped and why.
6. **Plan → DAG → validation.** The plan compiles to ordinary workflow JSON and goes through:
   - `schema.py`;
   - `graph.py` (cycles);
   - connector checks (unknown connector, type mismatch);
   - MCP `check_call` (unknown tool, bad arguments);
   - template references.

   A failure triggers at most **2 automatic repair calls** that include the exact errors. After that the user sees the error, never a silent failure.
7. **Plan review (View 7).** The "Here's what will happen" list from section 2, then one confirmation. A confirmed plan is saved as a **plan version**. Re-planning, or a changed fact sheet or connector set, creates version N+1, which needs confirming again. Older versions stay runnable for rollback.
8. **Advanced path stays.** Hand-written workflow JSON, `POST /validate` and `POST /runs` keep working for developers and CI. A graph view may exist under Advanced only.
9. **Data model additions:**
   - `plans(id, project_id, goal, created_at)`;
   - `plan_versions(plan_id, version, fact_sheet_hash, planner_connector, plan_json, workflow_json, dropped_json, created_by: planner|user, confirmed_at)`;
   - open gates persisted per D11.

**Acceptance:**
- With a stubbed LLM, a fact sheet with 3 real MCP tools plus a plan citing 1 invented tool yields a plan without the invented task, and that drop is shown in the review.
- A plan that creates a cycle or names a missing connector or unknown tool is repaired at most twice, then rejected with the exact reason.
- A plan with a payment step or a non-GET HTTP step always contains a gate before it, even if the LLM output didn't ask for one.
- Confirming creates a version; re-planning creates N+1 and the old version still runs.
- No test needs a network or a key.
- The security tests (6.6) are extended: a fake key placed in a scanned repo fixture never appears in any planner prompt, and instructions planted in a tool description or repo file don't change the plan's gating.

### Phase 6: Swap an app
A swap is just an auto-planned workflow (Phase 5) with redaction. View 3, spec in section 8.
- The user opens a slot (e.g. Payments) and fills the swap form. The Planner builds the migration plan from the form plus the repo fact sheet, and the user reviews and confirms it like any plan.
- Code-writing tasks run redact → LLM → verify → scan → restore, on a new git branch, with tests, behind a gate. A swap never edits the live branch.
- Slots: a connector belongs to a slot (`payments`, `reasoning`, …). A swap replaces the connector in a slot and leaves the project and other slots untouched.
- **Coding connector (after swap, D17):** the same branch → tests → diff → gate machinery, aimed at "add this connector to my code" instead of "replace". It never merges by itself, and the Planner re-checks afterwards so the map reflects the new code.

### Phase 7: Server + ROG workers (distributed)
Control plane on the Debian home server, workers on the ASUS ROG over Tailscale. Redis queue, idempotent steps, retries, dead-letter. The plan is in `FlowForge_Server_Orchestrator_Plan.md`. **Do not start this before Phase 4 is done.** Redis is used only for live traffic between machines; SQLite → Postgres is the storage ladder for teams.

### Phase 8: Visual builder for non-developers (later, not now)

---

## 6. Security and privacy spec (binding for all phases)

### 6.1 The promise (say exactly this, never more)
**API keys and other recognised secrets are never sent to an LLM, never written to logs, run history, cache, workflow JSON or the dashboard, and never committed to git.** The rest of the user's code and data still goes to whichever LLM they chose; for private code or customer data they should pick a local model (Ollama). Docs and UI must say "catches known key formats", never "catches everything".

### 6.2 Two doors, one vault
There are exactly two ways a secret enters FlowForge, and both end in the same vault and the same placeholder format:

| Door | When | What happens |
|---|---|---|
| **Form field** | The user types an API key into a connector form (Stripe, NIM, …) | The field is a *secret field*. The browser sends it once to `PUT /connectors/{id}/secret`. The server stores it in the vault and returns only `{"configured": true, "placeholder": "<REDACTED_STRIPE_KEY_1>"}`. **The connector JSON never contains the value, only `secret_ref`.** |
| **Existing code** | The swap/migration flow reads the user's repo and finds keys already inside it | The AST/regex scanner finds each key, moves it to the vault, and replaces it in the text with a placeholder before anything reaches an LLM. |

This means the key typed into a form is treated exactly like a key found in code: it becomes a placeholder + a vault entry at the moment it enters. The "form JSON" that is saved, logged, returned by the API, or put in an LLM prompt holds the placeholder or `secret_ref`, never the key.

### 6.3 Vault
- Module `flowforge/security/vault.py`.
- Storage: values encrypted with `cryptography` Fernet. Master key from `FLOWFORGE_MASTER_KEY` env var, else generated once at `~/.flowforge/master.key` with mode `0600`. Encrypted values live in a SQLite table `vault(secret_id, ciphertext, created_at)` or `~/.flowforge/vault.db`, **never** in `flowforge.db`'s plain tables, never in `.env` unless the user chose env-var restore (6.4).
- API: `put(secret_id, value) -> placeholder`, `get(secret_id) -> str` (**internal only**, callable from node construction and restore, never from a route), `has(secret_id) -> bool`, `delete(secret_id)`.
- Secret id format: `<CONNECTOR_ID>_<KIND>` upper-snake, e.g. `STRIPE_SECRET_KEY`. Placeholder format: `<REDACTED_{PROVIDER}_KEY_{n}>`, n counts per provider in one redaction pass, **the same value always gets the same placeholder within a pass**.
- There is no route that returns a secret value. Add a test that walks every route in `app.routes` and asserts no response body ever contains a known fake secret.

### 6.4 Redact → LLM → verify → scan → restore
Module `flowforge/security/redact.py` (pure functions, no I/O, easy to property-test):

```python
redact(text, vault) -> RedactResult(text, mapping)        # mapping: placeholder -> secret_id (never the value)
verify(llm_output, mapping) -> None | raises PlaceholderError   # every placeholder present exactly once; none invented, none edited
scan(text) -> list[Finding]                               # key-shaped strings still in the text → block
restore(text, mapping, vault, mode="env"|"literal", language=...) -> RestoreResult(text, env_additions)
```

Pipeline for any step that sends code or text to an LLM:
1. **Find**: (a) provider regexes (`sk_(live|test)_…`, `rzp_(live|test)_…`, `AIza…`, `nvapi-…`, `sk-ant-…`, JWT-shaped, PEM blocks) kept in `security/patterns.py`; (b) Shannon-entropy check on string literals assigned to names matching `key|secret|token|password|passwd|credential` (catches unknown formats); (c) **AST**: parse the file and inspect string literals and assignments/arguments, so a key buried in a function call, config object or f-string is found and its exact span replaced. Python files use the stdlib `ast`. JS/TS files use `tree-sitter` + `tree-sitter-javascript`/`-typescript` (add as an optional extra `flowforge[js]`; if unavailable, fall back to regex + entropy and **say so in the run event**).
2. **Redact**: replace each finding with a placeholder; value → vault.
3. **LLM edits** (sees placeholders only).
4. **Verify**: every placeholder returned exactly once; if the LLM dropped, duplicated, edited or invented one → **the run stops** with a `PlaceholderError` event. No auto-retry that could leak.
5. **Scan** the LLM output with the same finders: any key-shaped string present means the LLM invented or recalled one → block the result.
6. **Restore**. Default `mode="env"`: replace the placeholder with the language's env lookup (`process.env.STRIPE_SECRET_KEY`, `os.environ["STRIPE_SECRET_KEY"]`), write `STRIPE_SECRET_KEY=<value>` to the project's `.env`, and **ensure `.env` is in `.gitignore`** (add it, and fail loudly if the repo already tracks `.env`). `mode="literal"` puts the raw value in code; only allowed with an explicit `--allow-literal` and never when the target is inside a tracked git path. Literal restore is for local-only runs.
7. Only after restore does anything touch disk, and only on a **new git branch**, with tests, behind an approval gate (Phase 5).

### 6.5 Other guards and rules
- **Placeholders everywhere:** a logging filter (`security/logfilter.py`) installed on the root logger and uvicorn loggers redacts anything matching a known secret pattern or any value currently in the vault. SSE events, run results, cache rows and `flowforge.db` store the redacted form only. Test: put a fake key in a step param, run, then grep the DB file bytes, the SSE stream and captured logs for it. Zero hits.
- **Write-only secrets API:** request bodies containing secret fields are never logged (no body logging middleware). Secret fields in the UI are `type="password"`, `autocomplete="off"`, cleared from component state immediately after the PUT succeeds, never in `localStorage`, URLs or query strings.
- **Display:** a connected secret renders as `configured ••••••` or `missing`. Nothing else, no last-4, no length.
- **Test mode first:** payment connectors (Razorpay, Stripe) start in test mode. Live mode requires an explicit toggle and an audit log entry. Reject a live key (`sk_live_`, `rzp_live_`) saved on a connector whose mode is `test`, and the reverse.
- **Least access:** a node receives only its own connector's secret, resolved at construction or call time from `secret_ref`. No node can read another connector's vault entry. Risky steps (payments, deploys, code changes, anything with `side_effects: true`) wait at a gate.
- **Cache safety:** cache keys and values use the redacted resolved params. `llm` cached only at temperature 0 (existing rule). `mcp` stays opt-in. Never cache an output that failed `scan`.
- **PII (minimum viable):** connector setting `data_sent: "redacted_only"` runs a light redactor over prompts: emails, phone numbers, card-like numbers (Luhn-checked), plus any JSON paths listed in `redact_fields`. Document that this is pattern-based.
- **LLM proposals are data, never actions (D14).**
  - Planner output (plans, repair attempts, migration plans, code changes) is parsed into typed objects and validated. It is never executed, `eval`'d or shelled out.
  - Only the scheduler runs anything, and only after the user confirms the plan review.
  - Repo contents, API docs and tool descriptions fed to the Planner are **untrusted text** (prompt-injection risk). Instructions found inside them must not change the Planner's behaviour or the gating.
  - Whether a step is side-effecting, and so gated, is decided by code, never by the Planner. The LLM can add gates, never remove them.
  - A plan that adds a connector, widens access or turns on a side-effecting step is flagged in the plan review for explicit approval.
- **Logo uploads:** accept PNG/JPEG/WebP only (no SVG in v1, avoids script injection), max 1 MB, verified by magic bytes not extension, re-encoded or stored as-is under `~/.flowforge/logos/<connector_id>.<ext>`, served with `Content-Type` fixed and `X-Content-Type-Options: nosniff`, always rendered with `<img>`, never inlined.
- **Local command connector:** never `shell=True`, never string-interpolate params into a command, cwd restricted to a configured folder, env passed explicitly (do not inherit the whole environment).
- **CORS / network:** bind to `127.0.0.1` by default. Dashboard origin only. No auth system in v1 (single local user); when binding to `0.0.0.0` (Phase 7) require a token in a header. Do not add multi-user accounts yet.

### 6.6 Security tests (required, written first)
Use only obviously fake keys such as `sk_test_FAKEFAKE12345678`, `rzp_test_FAKE1234567`, `AIzaFAKEFAKEFAKEFAKEFAKE1234`. **Never put a real key in code, tests, fixtures, docs, commits or this file.**
- Property tests (hypothesis): `restore(redact(x)) == x` in literal mode for random text with embedded fake keys; `verify` rejects every mutation (drop, duplicate, edit, invent a placeholder); `scan(redact(x).text)` is empty.
- Golden tests: Python and JS snippets with keys in a call argument, an object literal, an f-string/template literal, a nested function, and a comment; each key found, span exact.
- Route walk: no response contains a fake secret (6.3).
- Leak test: fake key through a full mock run; grep DB bytes, SSE events, logs, cache rows.
- Gitignore test: env restore adds `.env` to `.gitignore` and refuses when `.env` is tracked.

---

## 7. Data model

### 7.1 Connector (what View 5 saves; secrets are references only)
```json
{
  "id": "image-studio",
  "type": "mcp",                       // llm | mcp | http | local
  "name": "Image studio",
  "role": "makes product photos",
  "slot": null,                        // e.g. "payments"; swap replaces the connector in a slot
  "style": {
    "color": "#E4572E",
    "logo": { "type": "letters", "text": "Is" }   // or {"type":"upload","file":"image-studio.png"} or {"type":"none"}
  },
  "connection": { "command": "npx", "args": "my-image-mcp" },   // fields depend on type (table below)
  "secret_ref": "vault:IMAGE_STUDIO_ENV_KEY",                   // null if none needed
  "mode": "test",                      // payment connectors: test | live
  "rate_limit_rpm": 40,
  "data_sent": "redacted_only",
  "fallback": null,
  "created_at": "..."
}
```

| type | `connection` fields | secret |
|---|---|---|
| `llm` | `provider` (`openai_compatible`\|`anthropic`), `base_url`, `model` | API key |
| `mcp` | `command`, `args`, `env_refs` | optional env secret |
| `http` | `base_url`, `auth_header` (name only), `auth_scheme` | API key / token |
| `local` | `command`, `cwd` | none |

Three ways to connect, to show in the UI: **log in (OAuth)**, **paste once (API key into the vault)**, **local command**. OAuth is Phase 4+ stretch: ship paste-once and local first.

### 7.2 Project, slot, board, widget
- **Project**: a name + a set of connectors + workflows + boards (the "baby-care shop" example). Table `projects`.
- **Slot**: a named role inside a project that holds one connector.
- **Widget**: one thing on screen (chart, status card, workflow graph). **Board**: a saved layout of widgets, stored as a small JSON file/row like a workflow. Ship two or three ready-made boards (e.g. "Finance Ops", "Security") so the first launch looks good.

### 7.3 Presets (v1 ships exactly these; each is just a connector template with a brand tile)
NVIDIA NIM (default, free), Gemini, Claude, Ollama (local), Razorpay, Stripe, `fetch` MCP server (`uvx mcp-server-fetch`). Plus **Custom** for each of the four types. Do not hard-code brands anywhere except `connectors/presets.py` and the tile colours.

### 7.4 Output viewers
Every step output has a `kind` hint chosen by the node, and the UI picks a viewer: `text` (LLM answers, logs), `table` (JSON arrays/objects), `chart` (series data, only when the step declares `viz: chart`), `image`, `media` (video/audio), `diff` (file or code change). Unknown kinds fall back to a JSON tree. Credits are tracked next to tokens in `usage` and surface in "Money and time".

---

## 8. The swap flow (Phase 6 spec) and gate design (Phase 5)

User story: a shop runs on Razorpay and wants Stripe. They open the Payments slot, press **Swap**, fill a short form, and FlowForge produces a git branch with the migration plus tests, for review. It never touches the live branch and never merges by itself.

1. **Form first** (answers beat a vague prompt): target provider, Checkout (hosted) or Elements, test or live, currency, webhook URL, repo path, test command, branch prefix (default `flowforge/`).
2. **Connect the new app** through the normal Add-app screen (key goes through the form door, 6.2).
3. **Migration plan = an auto-planned workflow (Phase 5, D14).** The Planner builds it from the form plus the repo fact sheet, and the user reviews it in the plan review (View 7) and confirms once, like any plan. Typically six tasks and one gate. Task names (sample data, verify against both providers' docs before relying on them): SDK + env var names; payment flow; DB column renames; webhook handler rewrite; checkout frontend; tests; then the human review gate. Only the code-writing tasks are `llm` steps. Mechanical tasks (rename env vars, run tests, create branch) are plain `local` steps. Independent tasks (e.g. payment flow and DB renames) run side by side, and the critical path sets total time. (Example numbers shown in the design: ~18 s sequential vs ~12 s parallel; do not hard-code them.)
4. **Per task:** gather the files → `redact` → LLM → `verify` → `scan` → `restore` → write to the branch.
5. **Run the repo's tests** on the branch (`local` step). Failing tests feed one bounded repair loop (max 2 attempts) back through the same redaction path.
6. **Gate:** show the diff + test result + the Sirius scan of the new code. Approve = leave the branch ready for the user to merge. Reject = delete the branch.
7. Known fact to respect in generated mappings: `contact_id` is a RazorpayX *payouts* concept; for payments the mapping is to `customer_id`. The webhook event rename is `payment.captured` → `payment_intent.succeeded`; signature verification moves from a hand-rolled HMAC to Stripe's library.

**Approval gate design (Phase 5; write as D11 before coding, together with D14):**
- Payments, code changes and every side-effecting step are always preceded by a gate; code decides what counts as side-effecting (D14), and no setting or plan can remove these gates.
- New `StepType` `"gate"`. A gate takes **no** global or type slot while waiting (it's waiting on a human, not a resource), has weight 0 in the critical-path DP by default, and the run status becomes `waiting` (new status) while any gate is open.
- Events: `gate_opened`, `gate_approved`, `gate_rejected`. Reject marks all descendants `skipped`, same as a failure.
- Persist open gates so a restart doesn't lose them. Optional `timeout_s` on a gate (default none).
- All five policies must schedule around gates identically; add a property test that a gate never changes the relative order of independent branches.

---

## 9. Working agreements

### 9.1 How to work
- **Plan mode first** for each phase and for anything touching `scheduler/`, `security/` or `schema.py`. Show the plan, wait for a yes.
- **Tests first** for `security/` and for any new scheduler behaviour. Offline only.
- **Small commits**, one logical change each. Branch per phase (`feat/phase-1-connectors`). Don't push to `main` directly once Phase 1 PR flow exists. Don't touch `DAA`.
- **Update docs in the same PR:** `DECISIONS.md` (new D-numbers), README quickstart, the status block in section 0, and the "Known limits" list in section 4 as they get fixed.
- When code and `DECISIONS.md` disagree, stop and ask which one is right.
- Keep dependencies few and free. New runtime dependency = justify it in the PR. Likely additions: `cryptography`, `anthropic`, `ruff` (dev), `tree-sitter*` (optional extra).
- Prefer the standard library and the existing patterns over new abstractions. No premature plugin systems.

### 9.2 Definition of done (every task)
1. `uv run pytest` green, offline. 2. `uv run ruff check` clean (after Phase 1 adds it). 3. Benchmarks still run (`sim --graphs 20 --k 4`). 4. New behaviour has tests, including a failure case. 5. Docs updated. 6. For UI: checked at phone width and in dark mode, keyboard-reachable, and no secret visible in the DOM.

### 9.3 Never
- Never add paid services to the default path, or tests that need a network or a key.
- Never log, print, commit or display a secret. Never write a real key anywhere.
- Never claim the redaction "catches everything" or that "the LLM never sees your code".
- Never edit a user's live branch or merge for them. Never skip a gate on payments or code changes.
- Never hand-draw a company logo or take one from anywhere but the CC0 `simple-icons` package (D15).
- Never change `DAA`. Never rewrite history on `main`.
- Never silently change a D-numbered decision; supersede it with a new one.

### 9.4 Style
Match the existing code: type hints, `from __future__ import annotations`, short docstrings that cite decisions `(D7)`, Pydantic models with `extra="forbid"`. Python backend, plain CSS tokens in the frontend, no UI component kit until it is clearly needed.

---

## 10. Config and files

`.env` (see `.env.example`): `NVIDIA_API_KEY`, `NIM_RPM`, `NIM_BASE_URL`, `NIM_DEFAULT_MODEL`. New in Phase 1+: `FLOWFORGE_DB`, `FLOWFORGE_HOME` (default `~/.flowforge`, holds vault, master key, logos, artifacts), `FLOWFORGE_MASTER_KEY` (optional), `FLOWFORGE_HOST` (default `127.0.0.1`). `.env`, `*.db`, `~/.flowforge` contents must stay git-ignored; add `.flowforge/` to `.gitignore` for local dev folders.

New directories you will create: `backend/flowforge/connectors/`, `backend/flowforge/security/`, `frontend/src/`, `docs/design/`, `.github/workflows/`.

---

## 11. First session script (what to do on day one of Phase 1)

1. Read this file, `DECISIONS.md`, `backend/flowforge/nodes/*.py`, `main.py`, `schema.py`, and `docs/design/system-map.html`.
2. Enter plan mode. Propose: the `Connector` models, the `connector` field on `Step`, how `rate_limit_key` becomes per-connector without breaking `NIM_RPM`, and the D10 entry text.
3. After approval: write D10, then tests for the provider-agnostic `LLMNode`, then the implementation. Then MCP discovery. Then the local command node. Then the registry. Then CI + CONTRIBUTING.
4. Open the PR with: what changed, what is still NIM-only, and the commands you ran.

---

## 12. Open questions: ask Vishwa, do not decide alone

1. **Frontend stack (next free D-number; D10 is connectors).** Default proposal: Vite + React + TypeScript, plain CSS with the design tokens, `frontend/dist` served by FastAPI, old `index.html` kept until parity. Alternative: stay buildless (htmx/Alpine). Confirm before scaffolding in Phase 2. Make sure `uv run uvicorn` still works for backend-only contributors.
2. **Package and CLI name.** Keep `flowforge`? (A `flowforge` command is proposed in Phase 2; check for PyPI name clashes before publishing.)
3. **JS/TS key detection depth.** Is `tree-sitter` as an optional extra acceptable, or should v1 ship regex + entropy only for JS/TS and use AST only for Python?
4. **OAuth connectors.** Ship in Phase 4, or defer until after the first public release? (Default: defer; paste-once + local first.)
5. **Where the design HTML lives.** Confirm the three artifacts get committed to `docs/design/`.
