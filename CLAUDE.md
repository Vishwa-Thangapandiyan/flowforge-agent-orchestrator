# CLAUDE.md

Guidance for Claude Code when working in this repository. Read this whole file at the start of every session. Then read the section of `DECISIONS.md` that matches the code you are about to touch.

---

## 0. Status (update this block at the end of every phase)

| | |
|---|---|
| Branch rules | `DAA` = frozen course project. **Never commit to it, never merge into it.** `main` = the product. |
| Current phase | **Phases 1–6 are merged into `main`** (one PR from `feat/flow-order`, a merge commit so every commit keeps its date; the four feature branches were deleted after). Phase 6 = flow order from code (D25), graph themes and the MCP Map (D26), advice you can act on (D27). D28/D29: FlowForge as an MCP server for coding agents is merged (`flowforge mcp`, five read-only tools, the Connect agent page). D30: the Connect page shows set-up, what the agent gets from this repo, and the agent's recent questions (merged). Phase 7 (D31, merged): security findings from the scan (keys in code and MCP configs, plain http, unpinned or whole-disk MCP servers), the Security page, map badges, `get_security_findings`. Phase 6b (D32, merged): flow order for Dart, JavaScript and TypeScript by patterns, the same flow, critical path and advice, `.wait` / `Promise.all` written out. D33: declutter: three header controls + ⋯, the flow one action at a time with decisions as ◆ marks, security as a ⚠ chip on the map (no Security page), a rail of Map · Checks · Connect agent (`feat/declutter`). **Branch rule from now on:** one short-lived branch per feature → PR → merge → delete the branch. Phase 8 part 1 (D34): an installable package (`pip install flowforge-map` / `uvx flowforge-map`; the command is `flowforge`) with the dashboard and example inside, a smoke test of the installed wheel on every PR, and a tag-triggered release to PyPI by trusted publishing (`feat/install`; the first upload waits for Vishwa's PyPI set-up). v0.1.0 is on PyPI as `flowforge-map`. D35: a map saved by an older reader (`Flow.reader` < `flowmap.planner.READER`) is read again on start; raise `READER` whenever the scan or flow reader changes what a map holds. D36: keys the coding agent never sees: `flowforge key add|list|remove|import` (typed hidden, the OS keychain or an encrypted file), `flowforge run -- CMD` (the app gets them), a 🔑 badge and a write-only box on the map, `get_keys` for the agent (names only) (merged; v0.2.0 on PyPI with D35). D37: Issues and Keys pages, Fix (FlowForge changes the code on a new branch) or Send to agent for every issue, and a key view behind a password + authenticator code (both merged; v0.3.0 is on PyPI). D38: lanes per kind in Boxed, `request_key` / `wait_for_keys` so the agent asks and waits for a key, and the Vault page (password, then code; every key's health) (merged; v0.3.0 is on PyPI). D39: projects: a home listing every project, one database each, `/p/<id>/` prefixes, a picker in the rail, the agent paired once (`flowforge mcp` serves every project, `list_projects`) (merged). D40: Settings (⚙ at the rail's bottom: your agent paired once, look, Keys & Vault status, data & checks, an update check only when pressed) and a three-step welcome the first time (merged). D41: a CLI that looks like FlowForge: a blue banner, offline status/projects/issues/settings, check plans, terminal scan summaries and key tables with plain/ASCII fallbacks (merged). D42: the desktop app (Tauri 2 in `desktop/`, FlowForge frozen by PyInstaller as its sidecar server, Browse… for folders, unsigned installers built by `.github/workflows/desktop.yml` on a tag) (merged). D43: masked keys: the agent gets `ffkey://NAME`, writes it where the key goes, and starts the app with `run_app`; FlowForge (plain code) fills the masks after the user allows the command once (`approve_runs`), with output masked (merged). D44: Add to code: the Keys page finds each key's spot (`file:line`), and one click puts a pasted key into the app: the Vault, the code's read, the git-ignored file the app reads (`.flowforge/dart-defines.json` + the Flutter Run config, `.env`, `.env.local`), never a code file (merged). D45: the settings a key needs (`SUPABASE_URL` with `SUPABASE_ANON_KEY`) are offered too, filled in from a Supabase key, never in the Vault; the health check uses the app's URL setting (merged). D46: a server that connects but doesn't reply is amber (busy), and checks send a standard User-Agent (merged). D47: the whole API answers only to this machine: a loopback connection, its Host, and a change's Origin. D48: each dependency keeps its newest 200 checks (merged). Vishwa's order: ① projects → ② settings + first run → ③ CLI → ④ Tauri; then the README, GIF and announcement. Next free D-number: D50. Roadmap (section 5, D23): 4 = repo scan, 5 = health checks + test results, 6 = flow order from code + critical path, 7 = security findings, 8 = launch, 9 = CLI agent + Tauri, 10 = V2 coding agents, 11 = FlowForge's own SLM |
| Direction | Point FlowForge at a repo. It finds every dependency (LLM, MCP server, HTTP API, local command) with `file:line` evidence and draws the map. It checks each one's health and security on demand and shows the test results. The scan is plain code and never sends code or keys to an LLM (D20). V2: a local coding agent adds a dependency on a branch for the user to approve (section 1, D19). Workflow JSON and the run API stay as the Advanced path |
| Done | Scheduler core, five policies, caches, SSE run stream, plain-HTML status page. Phase 1: D10 connectors (provider-agnostic `LLMNode`: openai_compatible + anthropic; per-connector buckets, cache namespaces, fallback), D12 MCP (tool discovery, schema-checked calls, non-text blocks, artifacts), D13 `local` step, connector registry + presets + `connectors.json`, HTTP connectors, ruff, CI (Linux + Windows), CONTRIBUTING. Phase 2 (D15, D16): dashboard (Vite + React + TS), persisted runs and events, minimal redaction (`security/logfilter.py`), connector create/edit/delete + logos, tool health, savings, example-data mode, `flowforge` command. Phase 3 (D17, D18): `flowmap/` (Flow JSON models, validation, code-inserted policy gates, critical path, overrides merge, version diff, `Planner` protocol + `FixturePlanner`), storage tables `flow_versions`/`flow_overrides`/`flow_positions`, `/flow*` and `/catalog` routes, 56-app catalog with mock test runs; dashboard: icon rail, flow map at `/` (React Flow + dagre, saved positions, search, legend, minimap, step panel with evidence and edits, test-run replay that holds at the gate), `/map/how`, `/map/recheck`, catalog at `/connectors`, money/time + app health on Runs, Geist fonts; Overview and HubMap removed; `Storage` calls serialised by a lock. Phase 4 (D19–D22): `scan/` (plain code, no network, no LLM: Python by `ast`, JS/TS and Dart by patterns, MCP configs, dependency files; stable ids, redacted evidence, confirmed/unconfirmed, coding-tool MCP servers as their own group), `presets.SERVICES` (22 services), `ScanPlanner` → dependency map (no gates, no critical path), one set of versions/edits/positions per map (`deps`, `flow`) with per-map numbering and in-place migration, `GET/POST /scan`, `?map=` on `/flow*`, `flowforge scan PATH`, `flowforge --repo PATH [--replace]`, `security.logfilter.redact_code`; dashboard: "Scan a folder" (empty state and header), scan view of "how it was mapped"; `examples/trip-planner` sample app. D23: example mode shows only the scanned map (the hand-made Baby-care flow is test data now), fake-data and test files skipped, a target from the host most URLs use, local blocks named for what they run. Phase 5 (D24): `checks/` (one harmless check per dependency, with no key, no cookie and no query: an API gets one GET, an LLM its model list, an MCP server is started in the repo folder with the SDK's minimal env and asked for its tools, a local program is only looked for), the `check` step type and `CheckNode` (run by the scheduler, at most 3 MCP servers at once), the `checks` table, `GET /checks`, `GET /checks/plan`, `POST /checks` (409 until you say yes to the exact MCP commands that will start), `GET /checks/{dep}`, "Test connection" for LLM and HTTP connectors, recorded results in example mode; dashboard: Check now with live progress over SSE, the first-check confirmation, health dots, edges and latencies on the map, Health (verdict, reason, likely fix, last checks) in the step panel, the Checks page (Runs moved under it as "Workflow runs (advanced)"), Approvals out of the rail. When a request cannot connect, the check says why (DNS, refused, silent, failed TLS) and whether your internet works. Phase 6 (D25, D26): `flow/` reads the order a repo's Python calls its dependencies (stdlib `ast`, nothing run): entry points, statement-level data and control dependencies, early returns, transitive reduction; decisions ask whole questions; weights are the last check's latencies (LLMs always estimates); advice groups calls that could start together, with a caveat when the code may stop before them; `CodeFlowPlanner` → the flow map (`Flow.source="code"`: no gates, writes marked by D25's rule); words from the code are masked. Dashboard: Dependencies/Flow switch, the Faster panel (as written vs could be, advice, critical path, limits), five map styles (Studio, Boxed with time columns, Blueprint, Metro, Soft) kept per viewer, lines that draw in, Watch it run (the could-be schedule), path tracing on hover and keyboard focus, and the MCP Map at `/map/export` (rules in `docs/mcp-map.md`; SVG, PNG 2×, PDF, Mermaid, Flow JSON). D27: each advice shows the `asyncio.gather` written out when safe, what to move by hand, and a prompt for a coding agent. 427 backend (on Linux; one test skips on Windows) + 80 dashboard tests pass offline; CI green on Linux and Windows |
| Not started | The launch README and packaging (8), Tauri (9), V2 (coding agents, vault, redact/verify/scan/restore, gates) (10), FlowForge's own SLM (11) |
| Next decision needed | Section 12. Ask Vishwa, don't guess. |

---

## 1. What we are building

**FlowForge maps what your app depends on, and tells you whether those dependencies are healthy and safe (D19).**

Point it at a repo. It finds every **dependency** the code uses and draws them as a map, each with the `file:line` it came from. A dependency is an LLM, an MCP server, an HTTP API or a local command. Then it checks each one:
- is the MCP server up and fast?
- is the API reachable, and is it on https?
- is a key hard-coded in the code?

The user runs the checks and tests whenever they want and sees the results on the map.

**Positioning.** Package scanners (Dependabot, Snyk, OSV) look at libraries, not the services an app calls. LLM tracing tools (Langfuse, LangSmith, Helicone) need code changes in the app. Service maps (Datadog) are enterprise products that need instrumentation. FlowForge is free and local, needs no change to the app, and its scan never sends code or keys to an LLM. Re-check this landscape before claiming it in the README.

- **Audience:** developers shipping apps that use LLMs and MCP servers, and anyone reviewing such a repo.
- **Open source.** MIT licence is already in the repo. This is Vishwa's long-term project, so first impressions matter as much as features: a one-command demo, the map, clear docs. Keep the README and CONTRIBUTING friendly to strangers.
- **No fixed deadline.** Prefer correct and tested over fast.
- **Hard constraint: zero cost by default.** No paid APIs or services in the default install, tests or CI. Free tiers (NVIDIA NIM) and local models (Ollama) only. Optional paid providers (Claude, Gemini, Stripe, Razorpay) work if the user brings their own key, and are never needed to run tests.
- **Local first.** SQLite, files on disk, one process. No cloud account, no Docker requirement, no Redis.
- **Privacy first (D20).** The scan is plain code and sends nothing to any LLM. FlowForge's own LLM is optional, off by default and chosen by the user, and it only sees masked findings, never file contents.

### The core user experience (D19)
FlowForge is an **LLMOps tool for apps that already use AI**, not an app builder.

1. **Scan.** `flowforge scan <folder>`, or "Scan a folder" in the dashboard. A GitHub URL comes later. Plain code finds the dependencies from:
   - SDK imports;
   - MCP config files;
   - dependency files;
   - URLs;
   - env var *names* (never values).
2. **Map.** The home page draws the repo and its dependencies, grouped by kind, each with its evidence. Pan, zoom, drag and search. A scan can miss things (a URL built at runtime, say), so the user can add, correct or hide a dependency. Each edit is an override and **never changes the user's code**.
3. **Check.** "Check now" runs a health check on each dependency, concurrently, under each one's rate limit (the checks per kind are in D19). The dots on the map turn green, amber or red. An optional timer comes later.
4. **See the results.** The Checks page shows every check and test result over time: status, latency, errors.
5. **Security.** The Issues page lists findings (hard-coded keys, `http://` APIs, risky MCP configs), each with Fix (FlowForge changes the code on a new branch) or Send to agent; the Keys page takes each key once. The map's ⚠ chip opens Issues and blocks wear badges (D37).
6. **Re-scan.** When the code changes, re-scan. FlowForge shows a diff, and the old version stays (D17).
7. **V2 (later).** The user adds a dependency on the map, and a local coding agent writes the code on a branch for them to approve.

Under the hood, the DAG scheduler runs the checks: critical path, five policies, rate limits, caches. Hand-written workflow JSON and the run API stay as the **Advanced** path for developers and CI.

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

**Page changes from D19:**
- **Map** stays home. It draws the scanned dependency map in the same visual language.
- **Runs** becomes **Checks**: health and test results per dependency.
- **Security** shows the scan's findings instead of a vault demo.
- **Approvals** is hidden until V2 (Phase 10).

The new Checks and Security layouts need artboards Vishwa approves before they are built.

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
| 7 | *Dropped (D17).* Plan review: "Here's what will happen", one confirmation | Nothing | none |

View 7 (plan review) was dropped by D17: the map is the plan. Under D19 there is no plan to review in V1.

Logos (D15): preset brands use the **CC0 SVG marks from the `simple-icons` package**, inside a brand-colour tile, only to identify the integration (nominative use; never altered, never implying endorsement). A brand that isn't in the package, and Sirius, gets a two-letter monogram tile. Custom apps use letters + colour or the user's uploaded image (rules in section 6.5). Never hand-draw a company logo or copy one from a brand site.

---

## 3. Architecture (target)

**Scan the repo, then check what it found (D19). Every call to a dependency goes through FlowForge core.**

```
                ┌──────────── dashboard (browser; Tauri in Phase 9) ────────────┐
                │        Map · Dependencies · Checks · Security                 │
                └──────────────▲─────────────────────────────┬─────────────────┘
                         SSE events                         REST
┌──────────── FlowForge core (FastAPI, one process) ─────────┴──────────────────┐
│  scan/      repo → dependencies + evidence + findings, no LLM (D20) ← Phase 4 │
│  flowmap/   map versions, overrides, re-scan diff                   ← built   │
│  checks     health + tests per dependency, run by the scheduler     ← Phase 5 │
│  scheduler  Kahn, critical path, HLFET, rate limits, caches         ← built   │
│  connectors + nodes (llm, mcp, http, local)                         ← built   │
│  security/  key finders, redaction, log filter                      ← 2 + 6   │
│  storage    SQLite                                                            │
└──▲─────────────────▲──────────────────▲──────────────────▲───────────────────┘
   │ reads           │ llm              │ mcp              │ http / local
 your repo        LLMs it uses     MCP servers it uses   APIs, scripts it uses
 (read-only)
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
- Secrets resolve from `env:` refs only; `vault:` refs are refused until the vault lands (V2, Phase 10). D36's key store (keychain or encrypted file) is for the user's app (`flowforge run`), not yet for connectors. Since Phase 2 a minimal redactor (D16) masks known key shapes and configured key values in stored runs, events, cache rows, API results and logs; it is pattern-based, not the full V2 pipeline (6.4).
- Connectors can be added and edited from the dashboard (D16); those from `connectors.json` are read-only there. "Test connection" works for every type; for LLM and HTTP it is the health check's one request, without the key (D24).
- The default `mcp` node is still the V1 node (it accepts `params.server`); the `fetch` connector is separate, so `mcp` and `fetch` may each spawn their own fetch server.
- On Windows, killing a timed-out `local` process does not kill its children.
- Runs that were running when the server stopped are marked `interrupted`; they are not resumed.
- Live run has Stop but no Pause (a pause would change the scheduler).
- The hand-made Baby-care flow (`FixturePlanner`) is test data only, for the flow-map code (gates, the Test run replay of a recorded trace). Catalog test runs are canned mocks.
- Flow order from code (D25, D26) limits:
  - Python by the AST; Dart, JavaScript and TypeScript by patterns (D32), labelled less exact. Their reader blanks comments and strings, then matches functions and statements; unusual syntax (a regex literal holding a quote, a statement split oddly without `;`) can confuse it.
  - Dart/JS/TS calls are followed by name (same class, same file, then a name unique in the repo); a method called on an object (`provider.load()`) isn't followed, so a callback's target becomes its own entry point.
  - Service SDK calls are recognised through a client named in `presets.CLIENTS` (Supabase, Firebase) and names bound to it; other SDKs count only through their URLs.
  - Advice never reaches across an early stop (a call after `if (x == null) throw` waits for the check): whether it should is open question 7.
  - It can't see calls passed around as values, callbacks or dynamic dispatch, and doesn't follow into other entry points' helpers (the Faster panel says so).
  - Advice groups calls by the same earliest start; the spec's "four first calls as one card" reading is a question for Vishwa (section 12).
  - Weights are the last check's latencies; LLMs and anything unchecked are estimates (`DEFAULT_MS`). A block reached through a server adds no time.
  - Boxed's time-column layout isn't saved (it is recomputed, Re-tidy included); Blueprint has no dimension lines yet.
  - The written change (D27) covers async calls in one block, each a plain `x = await …`; the rest of an advice is listed to move by hand, and every advice has a prompt for a coding agent. Nothing is ever applied.
  - A block reached through a server is recognised by its `what` ("through fetch"), not a field of its own.
  - On a dependency map's MCP Map, a through-a-server line can cross other labels.
  - The MCP Map's PNG uses system fonts (an SVG drawn as an image can't load web fonts); Mermaid output isn't checked against GitHub's renderer in tests.
  - `FlowMapPage.tsx` is about 620 lines (the scan form, action picker and legends are their own files); its `MapView` still switches on dependency / code / Planner maps in many places, and splitting that per map kind is due.
- Repo scan (D21, D22) limits:
  - JS/TS and Dart are read by patterns, line by line, so a call split across lines can be missed. Python uses the AST.
  - The dependency map is laid out by dagre in one column, ordered by kind; it isn't drawn in lanes per kind yet.
  - A dependency's `places` count isn't shown in the step panel yet.
  - Start-up scans the chosen folder when it has no map yet, inside the server's start-up, so a very large repo delays start-up.
  - Example mode scans the trip planner shipped inside the package (D34), or `examples/trip-planner` in a checkout.
  - Block ids `app` and `tools` (the two start blocks) are repeated in the dashboard instead of coming from the API.
- Security findings (D31) limits:
  - Known key formats, plus values of 16+ characters with high entropy given to key-like names; a key of an unknown shape under an ordinary name is missed.
  - Test and fake-data files aren't searched (they are skipped by the scan, D23), so a real key left in a test file isn't reported.
  - A finding can't be dismissed yet (a key that is public by design, such as some client-side keys, stays listed).
  - Git history isn't read: a key removed from the code but still in history isn't found; every key fix says to replace the key.
  - The opt-in check of SDK versions against osv.dev is not built.
- Keys (D36) limits:
  - An agent that can run commands as the user can still `flowforge run -- printenv` or read the keychain; the promise is "never handed to the agent, not left in files".
  - On Linux the Secret Service lets any program of the same user read a key without asking; the file store's master key sits beside it in `~/.flowforge` (mode 0600), so it guards against a copied file, not against the user's own programs.
  - MCP servers a coding tool starts get their env from that tool; FlowForge can't feed them.
  - A key already written in code is reported (D31) but not moved into the store yet (it edits code: Phase 10).
  - A key is tied to a dependency when the scan sees it read on the dependency's line, when its name names the service (`STRIPE_…` → Stripe), or when its file has only one dependency; otherwise it is listed without a block.
  - Changes to the key store take a lock file in `~/.flowforge` (`keys.lock`), so two `flowforge key add` at once lose nothing; reads don't wait.
  - The whole API answers only to this machine: a loopback connection, its Host, and a change's Origin (D47). A program running as the user can still call it.
- Issues and fixes (D37) limits:
  - Fix covers a key that is a whole string literal in Python, or in JS/TS that shows it runs on Node (browser code has no `process.env`). A key inside a longer string (`"Bearer …"`), an f-string, a comment, Dart, or any MCP config goes to the agent. A later Fix for `.mcp.json` could wrap the server's command in `flowforge run`, so only the server gets the key.
  - Fix needs git, a first commit, and the file committed; it uses your git identity and runs your hooks (a failing hook leaves no branch).
  - A Python fix reads the key with `os.environ["NAME"]`, so the app fails at start without it (use `flowforge run`).
  - "Send to agent" waits until you tell your agent; FlowForge doesn't start it (Phase 10).
  - The Issues page reads the code fresh; the map's badges follow the saved map until a re-scan.
- Projects (D39) limits:
  - A project's state is built the first time it is opened and kept until FlowForge stops; many big projects open at once use more memory.
  - "Back where you left it" (page, map view, open block) lasts while the dashboard tab is open; the open-projects list is kept in this browser.
  - In the browser a new project's folder is typed (there's no folder picker); the desktop app (④) can open the system's.
- Keys the agent asks for (D38) limits:
  - `wait_for_keys` waits at most 110 s per call (MCP clients time out long calls); the agent calls it again.
  - The new block appears after the user reviews the re-scan the banner opens; FlowForge doesn't add it by itself (D17).
  - In Boxed, a line from a server to an API it reaches crosses the gap between their lanes; lanes aren't saved (like time columns).
- Vault (D37, D38) limits:
  - An agent that can run commands as the user can still read the keychain or files, or run `flowforge lock reset --forget` and set its own lock; the dashboard shows the reset until the next unlock.
  - Sessions and step 1's 2-minute ticket live in the dashboard's process: restarting FlowForge locks the Vault.
  - Setting up a lock when none exists needs no proof: whoever reaches the dashboard first (on this machine) sets it.
  - A forgotten password plus a lost phone means `--forget`; there are no recovery codes.
- Settings and the welcome (D40) limits:
  - The theme and map style are kept per browser (the map style is also saved in `settings.json` for a browser that has none).
  - "Connected" means your agent has asked about some project; it doesn't prove the agent's config is still in place.
  - The welcome shows only while there are no projects; someone upgrading with projects never sees it (Settings has everything it sets up).
  - Check for updates compares version numbers only; it doesn't install anything.
- CLI (D41) limits:
  - `check` prints an offline plan; checks and approval of exact MCP commands stay in the dashboard.
  - Status, project counts and issues follow the saved dependency scan, so code changes need a dashboard re-scan; `key list` reads the folder fresh.
  - Saved key status in project summaries means on record (names only); `key list` still verifies readability as before.
- Desktop app (D42) limits:
  - Unsigned: macOS and Windows warn once (the README shows how to open it).
  - About 50–80 MB per installer (Python is inside); the one-file server unpacks itself at each start (a second or two).
  - No auto-update: Settings' Check for updates says when a new version is out.
  - `cargo clippy`/`rustfmt` aren't installed on Vishwa's Fedora (they need admin rights to add); CI runs both.
  - Browse… needs the window's local page to reach Tauri; in a browser there is no Browse (a page can't read a path).
- Add to code (D44) limits:
  - The value sits in a hidden git-ignored file next to the app (`.flowforge/dart-defines.json`, `.env`, `.env.local`); Claude Code is told not to read it (`.claude/settings.local.json`), other agents aren't.
  - A spot is a line that reads a key-like env name, a key-like name given a placeholder, or a whole key in a string. A key built from parts, read through the app's own helper, or named just `key` isn't found.
  - Python or Node that loads no `.env` gets Save (the Vault) only; `run_app` passes the key.
  - A terminal `flutter run` needs `--dart-define-from-file=.flowforge/dart-defines.json`; the IDE's Run doesn't. A `launch.json` with comments isn't rewritten.
  - Writes go to the working files directly (not a branch, nothing committed); a line that changed since the page showed it is refused.
  - Settings (D45) are offered only when their first word matches a key's (`SUPABASE_URL` ↔ `SUPABASE_ANON_KEY`) and they have no default; a URL is suggested only from Supabase's old JWT anon key. The agent's own checks don't use app settings (its server never opens a file that holds keys).
- Masked keys (D43) limits:
  - `run_app` needs FlowForge running (the desktop app or `flowforge`); without it the agent is told to open it.
  - Approval is per exact argument list: a different flag is a new command and asks again.
  - Runs and waiting requests live in FlowForge's process: restarting it stops runs and forgets unanswered requests (allowed commands are kept).
  - Masks are filled in commands and the environment only; a `.env` line works through the environment (loaders keep a variable already set), but other config files and assets (flutter_dotenv) see the mask: read the env var or use `--dart-define`.
  - Output keeps the last 2000 lines of a run.
- MCP server (D29) limits:
  - The agent's command follows the install (D34): a checkout uses `uv --directory`, `uvx` pins the version, a `pip` install uses its own Python.
  - The agent's map is as scanned: edits made on the dashboard's map (hidden or added blocks) aren't applied to it.
  - Checks, latencies and the yes to start MCP servers are shared only when the dashboard maps the same folder (`--db` names the dashboard's database). In example mode the dashboard keeps no repo setting, so they aren't shared there.
  - Antigravity's config file location differs between versions; the page says so. Codex's set-up is checked against its docs, not run here.
- Health checks (D24) limits:
  - No timer: checks run when you press Check now (section 12, question 2).
  - No authenticated checks: a check never uses a key (D24 records how an opt-in one must work).
  - A check is one request: any answer below 500 counts as up, so a POST-only endpoint answering 405 is "up". Public servers can throttle repeated checks; Overpass stalls a computer that asks often, so a connection with no reply is amber "Connected, but no reply", not down (D46).
  - The first check of an `npx`/`uvx` server includes its download, so it often shows as slow.
  - Each dependency keeps its newest 200 checks (D48).
  - At most 3 MCP servers start at once; the limit sits in `CheckNode`, not the scheduler, and MCP step timeouts grow with the number of rounds.
  - Example mode's results are recorded, not live (D16).
- Map gates are inserted by code (D17), but scheduled runs have no gate step yet (D11, V2). A GET to a payment API isn't gated; any other method is, and an HTTP block with no method counts as a write (D17).
- `Storage` shares one SQLite connection across the threadpool, so every public method takes one `RLock` (a race existed since sync connector routes; `test_storage_threads.py`). Fine for one local user; revisit if a server version comes (section 5, "Later, maybe").
- On a phone the map's zoom buttons are hidden (pinch to zoom).
- One action's flow is laid out fresh each time it is picked; dragging its blocks isn't saved (D33).
- Each page loads when it is opened: the first download is about 363 kB (121 kB gzipped); the map's React Flow + dagre (190 kB) load with the map.
- Timing-sensitive tests: tests assert scheduling decisions, not wall-clock windows. Exception: `actual_critical_path` in `test_diamond_meets_lower_bound` still depends on measured durations; it held in 500 stress runs.

### Rules that already exist and must not break
- `DECISIONS.md` is the spec: D1–D9 (V1), D10 connectors, D11 approval gates (reserved for V2), D12 MCP connectors, D13 local command step, D14 plan from connectors, D15 frontend stack, D16 run history + redaction + example mode + editable connectors, D17 the flow map, D18 frontend additions (Geist, React Flow, dagre), D19 the product direction (repo → dependency map → health, security and tests; also renumbers the roadmap), D20 a scan with no LLM and an optional, user-chosen LLM that sees only masked findings, D21 the scanner contract, D22 scanner rules learned from the first real scans, D23 no hand-drawn maps and the roadmap after the first look, D24 health checks, D25 flow order from code, the critical path and "run these together", D26 graph themes with motion and the MCP Map, D27 advice you can act on, D28 two optional brains with FlowForge as an MCP server, D29 the MCP server's five tools, D30 the Connect page (what your agent gets, what it asked), D31 security findings from the scan, D32 flow order for Dart, JS and TS, D33 declutter (three controls, the rest one click away), D34 an installable package, D35 maps from an older reader are read again, D36 keys the coding agent never sees, D37 Issues and Keys pages, click-to-fix and the 2FA key view, D38 map lanes, keys the agent asks for, and the Vault, D39 projects: a home with every project and a picker in the rail, D40 Settings and a welcome the first time, D41 a CLI that looks like FlowForge, D42 a desktop app with Python inside, D43 masked keys the agent places and FlowForge fills, D44 Add to code, D45 the settings a key needs, D46 busy servers are amber and checks name themselves the standard way, D47 the whole API answers only to this machine, D48 each dependency keeps its newest 200 checks, D49 `npx flowforge-map` with no Python. Cited in code as `(D7)` etc. Keep code and doc in agreement. **New decisions get the next free number (D50, …) in the same format**, written *before* the code.
- Say "concurrent on one event loop (I/O-bound)", never "parallel on CPUs" (D4).
- Benchmarks must keep running unchanged (`benchmarks/`). Don't change the five policies' behaviour to make a new feature easier.

---

## 5. Roadmap and acceptance criteria

Work in this order. Each phase = one branch `feat/<name>`, one PR into `main`, tests green, `DECISIONS.md` updated, status block (section 0) updated. **Start every phase in plan mode** and show Vishwa the plan before editing. Phases 1–3 were planned under the old direction and are kept here as history; D19 renumbered everything from Phase 4 on.

### Phase 1: Any LLM, any MCP server  *(done, merged)*
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

### Phase 3: Flow map V1  *(D17, D18; artboards in `docs/design/flow-map-artboards/`; done, merged)*
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

### Phase 4: Repo scan V1  *(D19–D22; done, merged)*
Goal: point FlowForge at a folder and get a real dependency map, with evidence, without any LLM.

1. **Sample project `examples/trip-planner/`** (Python), "plan a day in a city". It is the scanner's test case, the demo and the new example map, replacing the Baby-care fixture. It uses only free, keyless pieces:
   - Ollama (`llama3.1:8b`), through the OpenAI-compatible SDK;
   - keyless MCP servers in `.mcp.json`: `mcp-server-time`, `mcp-server-fetch` (uvx) and `server-filesystem` (npx), plus a local `currency` server that is broken on purpose;
   - Open-Meteo (weather), Nominatim (place → coordinates), OSRM (routes);
   - one local script.

   It also plants three things for the checks to find: one **fake** hard-coded key, one plain `http://` URL, and one deliberately broken MCP server. It runs for real when Ollama and the network are there, but no test needs either.
2. **D21, the scanner contract, before any code:**
   - what counts as a dependency;
   - how dependencies are named and merged;
   - the evidence format;
   - the output JSON;
   - how the output becomes the map (reusing the Flow JSON and versions from D17 where they fit).
3. **`scan/`:**
   - Python through the stdlib `ast`;
   - JS/TS and Dart through patterns;
   - dependency files (`pyproject.toml`, `requirements.txt`, `package.json`, `pubspec.yaml`);
   - MCP configs (`.mcp.json`, `mcp.json`, `.vscode/mcp.json`, `claude_desktop_config.json`);
   - URL hosts and env var names.

   Every finding has a `file:line`. Vendored, build and ignored folders are skipped.
4. **Entry points.** `flowforge scan <path>` prints JSON and can open the map. The dashboard gets a "Scan a folder" entry. The map draws the dependency map, and re-scan → diff → versions reuses D17.

**Acceptance:**
- Scanning `examples/trip-planner` finds every dependency planted in it with the right `file:line`, and nothing else.
- Scanning `~/Documents/smart-travel-assistant` (Flutter) finds Supabase, the OpenStreetMap tiles, OSRM, Overpass and Wikimedia.
- A test proves the scan makes no network call and no LLM call (D20).
- The fake key's value appears in no stored row, API response or log.
- All tests run offline. The scheduler and benchmarks are untouched.

### Phase 5: Health checks and test results  *(D24; done, merged)*
- **"Check now"** works for one dependency or for all of them.
  - Every dependency gets the generic checks for its kind (D19); catalog apps get better recipes.
  - The scheduler runs the checks concurrently under rate limits.
  - "Test connection" for llm and http lands here.
- **Runs becomes Checks:** the latest status per dependency, history, latency and errors. The dots on the map show health.
- Results are stored over time. An optional timer comes at the end of the phase if Vishwa wants it (section 12).

**Acceptance:**
- The trip planner's broken MCP server shows as down, with the reason.
- A slow stub dependency shows its latency.
- Tests use stub servers and no network.

### Phase 6: Flow order from code + critical path  *(D23, D25–D27, D32; done: Python by the AST, Dart and JS/TS by patterns)*
The order the app calls its dependencies in, from the code, so FlowForge can say what slows the app down and what could run together. Nothing on it is drawn by hand: every block and line keeps its `file:line`.
- **Python first, through the AST.** A call that uses another call's result depends on it, which gives a real DAG of the app's calls. Decisions (`if` branches) show where they are in the code. JS/TS and Dart follow, honestly labelled when they're less exact.
- **Critical path** with the existing DP, weighted by Phase 5's measured latencies, labelled as estimates.
- **Suggestions:** "these calls don't depend on each other: run them together, about N ms saved", each pointing at the code.
- The flow map's existing pieces (critical path view, gates before side effects, the Test run replay) are reused.

**Acceptance:**
- In `examples/trip-planner`, the independent calls (ip-api, Nominatim, the fetch and currency servers) are found as able to run together, with `file:line`.
- Every line on the flow map points to code. No test needs a network or a key; the scheduler and benchmarks are untouched.

### FlowForge as an MCP server  *(D28, D29; done)*
Coding agents (Claude Code, Codex, Antigravity) connect to FlowForge with one MCP config entry.
- Read-only tools first: `get_map`, `get_advice`, `run_checks`, then `get_security_findings` once Phase 7 lands.
- Everything returned is masked like evidence; no key value ever.
- The agent changes code on a branch; FlowForge re-scans; the user approves. FlowForge never edits code.
- FlowForge's own LLM stays an optional fallback (D20), later the SLM (Phase 11).

**Acceptance:** an in-process MCP client lists the tools and gets the trip planner's map and advice offline; a fake key in the repo appears in no tool result; no test needs a network or a key.

### Phase 7: Security findings  *(D31; done)*
- **Hard-coded keys,** found with the §6.4 finders:
  - known key patterns + entropy;
  - the Python AST;
  - JS/TS and Dart by pattern.
- **Other findings:**
  - `http://` APIs;
  - risky MCP configs: broad filesystem roots, unpinned `npx`/`uvx` packages, secrets passed as plain `env`;
  - later, and opt-in because it sends package names to osv.dev: SDK versions with known vulnerabilities.
- **On the map** (D33): a ⚠ chip lists the findings, each with its fix; blocks with findings wear a badge.
- **Golden tests** for the finders (§6.6).

**Acceptance:** the planted fake key and `http://` URL are reported with `file:line`, and the key's value appears nowhere: DB bytes, API responses, logs, the DOM.

### Phase 8: Launch
- **Docs:** rewrite the README around the one-command demo, record a demo GIF, write a short "how it works".
- **Install:** `npx flowforge-map` first (D49, no Python), then `uvx flowforge-map` / `pipx install flowforge-map`, or the desktop app (D34: `flowforge` is blocked on PyPI by `flow-forge`; the command stays `flowforge`).
- **Release:** CI green, first tagged release, merge into `main`.

### Phase 9: CLI agent + Tauri desktop app
- A richer CLI.
- The same React frontend in Tauri, with the Python backend as a sidecar.
- Signing for macOS and Windows.

### Phase 10 (V2): Coding agents add dependencies
The user adds a dependency on the map. A local coding agent then writes the code:
- Claude Code (`claude -p` or the Agent SDK; it needs no VS Code), Codex (`codex exec`), or Antigravity if it can run headless (section 12);
- on the user's own subscription;
- on a new branch or worktree.

Safety, in order:
1. Isolate keys first: the auto-fix moves hard-coded keys into `.env`.
2. Deny the agent read access to `.env`.
3. Mask what FlowForge passes to it.
4. Run the tests.
5. The user approves the diff (D11 gates). Nothing merges by itself.
6. FlowForge re-scans afterwards.

This phase carries the old specs: the vault and redact → verify → scan → restore (§6.2–6.4), and the swap and gate design (§8).

### Phase 11: FlowForge's own SLM  *(D23)*
A small language model run locally, with proper guardrails and algorithms, replacing the dependence on hosted APIs (NIM or others) for anything FlowForge itself needs an LLM for. Plain code stays the source of truth: the SLM's proposals are data, checked against the code before they reach a map (D14), and it sees masked findings only (D20).

### Later, maybe
- Server + workers (`FlowForge_Server_Orchestrator_Plan.md`) for scheduled monitoring on a home server.
- The visual builder for non-developers is dropped: FlowForge is not an app builder (D17, D19).

---

## 6. Security and privacy spec (binding for all phases)

**What applies when (D19, D20):**
- **V1 (Phases 4–8):** the finders in 6.4 step 1 (patterns, entropy, AST) power the scan's security findings. The storage, display and logging rules in 6.5 apply everywhere.
- **V2 (Phase 10):** the vault (6.2–6.3) and the full redact → LLM → verify → scan → restore pipeline (6.4) are needed when a coding agent edits code.

### 6.1 The promise (say exactly this, never more)
**API keys and other recognised secrets are never sent to an LLM, never written to logs, run history, cache, workflow JSON or the dashboard, and never committed to git.** This includes FlowForge's own optional LLM, and the scan sends nothing to any LLM (D20). Code or data the user sends to an LLM through their own app is outside FlowForge; for private code or customer data, a local model (Ollama) is the safe choice. Docs and UI must say "catches known key formats", never "catches everything".

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
1. **Find**: (a) provider regexes (`sk_(live|test)_…`, `rzp_(live|test)_…`, `AIza…`, `nvapi-…`, `sk-ant-…`, JWT-shaped, PEM blocks) kept in `security/patterns.py`; (b) Shannon-entropy check on string literals assigned to names matching `key|secret|token|password|passwd|credential` (catches unknown formats); (c) **AST**: parse the file and inspect string literals and assignments/arguments, so a key buried in a function call, config object or f-string is found and its exact span replaced. Python files use the stdlib `ast`. JS/TS and Dart use patterns + entropy in V1 (section 12); V2 may add `tree-sitter` as an optional extra `flowforge[js]`, falling back to patterns + entropy and **saying so** when it isn't installed.
2. **Redact**: replace each finding with a placeholder; value → vault.
3. **LLM edits** (sees placeholders only).
4. **Verify**: every placeholder returned exactly once; if the LLM dropped, duplicated, edited or invented one → **the run stops** with a `PlaceholderError` event. No auto-retry that could leak.
5. **Scan** the LLM output with the same finders: any key-shaped string present means the LLM invented or recalled one → block the result.
6. **Restore**. Default `mode="env"`: replace the placeholder with the language's env lookup (`process.env.STRIPE_SECRET_KEY`, `os.environ["STRIPE_SECRET_KEY"]`), write `STRIPE_SECRET_KEY=<value>` to the project's `.env`, and **ensure `.env` is in `.gitignore`** (add it, and fail loudly if the repo already tracks `.env`). `mode="literal"` puts the raw value in code; only allowed with an explicit `--allow-literal` and never when the target is inside a tracked git path. Literal restore is for local-only runs.
7. Only after restore does anything touch disk, and only on a **new git branch**, with tests, behind an approval gate (V2, Phase 10).

### 6.5 Other guards and rules
- **Placeholders everywhere:** a logging filter (`security/logfilter.py`) installed on the root logger and uvicorn loggers redacts anything matching a known secret pattern or any value currently in the vault. SSE events, run results, cache rows and `flowforge.db` store the redacted form only. Test: put a fake key in a step param, run, then grep the DB file bytes, the SSE stream and captured logs for it. Zero hits.
- **Write-only secrets API:** request bodies containing secret fields are never logged (no body logging middleware). Secret fields in the UI are `type="password"`, `autocomplete="off"`, cleared from component state immediately after the PUT succeeds, never in `localStorage`, URLs or query strings.
- **Display:** a connected secret renders as `configured ••••••` or `missing`. Nothing else, no last-4, no length. The one exception is the locked key view (D37): after a password and an authenticator code, masked until Show, hidden again after 30 s, locked after 5 minutes.
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
- **CORS / network:** bind to `127.0.0.1` by default. Dashboard origin only. No auth system in v1 (single local user); when binding to `0.0.0.0` (server + workers, later) require a token in a header. Do not add multi-user accounts yet.

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

Three ways to connect, to show in the UI: **log in (OAuth)**, **paste once (API key into the vault)**, **local command**. OAuth is V2 at the earliest: ship paste-once and local first.

### 7.2 Project, slot, board, widget
- **Project**: a name + a set of connectors + workflows + boards (the "baby-care shop" example). Table `projects`.
- **Slot**: a named role inside a project that holds one connector.
- **Widget**: one thing on screen (chart, status card, workflow graph). **Board**: a saved layout of widgets, stored as a small JSON file/row like a workflow. Ship two or three ready-made boards (e.g. "Finance Ops", "Security") so the first launch looks good.

### 7.3 Presets (v1 ships exactly these; each is just a connector template with a brand tile)
NVIDIA NIM (default, free), Gemini, Claude, Ollama (local), Razorpay, Stripe, `fetch` MCP server (`uvx mcp-server-fetch`). Plus **Custom** for each of the four types. Do not hard-code brands anywhere except `connectors/presets.py` and the tile colours.

### 7.4 Output viewers
Every step output has a `kind` hint chosen by the node, and the UI picks a viewer: `text` (LLM answers, logs), `table` (JSON arrays/objects), `chart` (series data, only when the step declares `viz: chart`), `image`, `media` (video/audio), `diff` (file or code change). Unknown kinds fall back to a JSON tree. Credits are tracked next to tokens in `usage` and surface in "Money and time".

---

## 8. The swap flow and gate design (V2, Phase 10)

> Written under the old roadmap (old phase numbers below). It still describes how V2's coding agents must work: a new branch, redaction, tests, a gate, and no merging by itself. The "Planner" and "plan review" parts are replaced by the user adding a dependency on the map (D19).

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
- Never log, print, commit or display a secret (displaying: only in D37's locked key view). Never write a real key anywhere.
- Never claim the redaction "catches everything" or that "the LLM never sees your code". "The scan sends nothing to an LLM" is true and allowed (D20).
- Never edit a user's live branch or merge for them. Never skip a gate on payments or code changes.
- Never hand-draw a company logo or take one from anywhere but the CC0 `simple-icons` package (D15).
- Never change `DAA`. Never rewrite history on `main`.
- Never silently change a D-numbered decision; supersede it with a new one.

### 9.4 Style
Match the existing code: type hints, `from __future__ import annotations`, short docstrings that cite decisions `(D7)`, Pydantic models with `extra="forbid"`. Python backend, plain CSS tokens in the frontend, no UI component kit until it is clearly needed.

---

## 10. Config and files

`.env` (see `.env.example`): `NVIDIA_API_KEY`, `NIM_RPM`, `NIM_BASE_URL`, `NIM_DEFAULT_MODEL`. New in Phase 1+: `FLOWFORGE_DB`, `FLOWFORGE_HOME` (default `~/.flowforge`, holds vault, master key, logos, artifacts), `FLOWFORGE_MASTER_KEY` (optional), `FLOWFORGE_HOST` (default `127.0.0.1`). New in Phase 4: `FLOWFORGE_REPO` (the folder to map; set by `flowforge --repo`) and `FLOWFORGE_REPO_REPLACE=1` (set by `--replace`: a different folder starts a fresh map). Neither is a secret. `.env`, `*.db`, `~/.flowforge` contents must stay git-ignored; add `.flowforge/` to `.gitignore` for local dev folders.

New directories you will create: `backend/flowforge/connectors/`, `backend/flowforge/security/`, `frontend/src/`, `docs/design/`, `.github/workflows/`.

---

## 11. Start of every session

1. Read this file, section 0 first, then the `DECISIONS.md` entries for the code you will touch. D19 and D20 apply to anything product-facing.
2. Check `git status` and the branch. Never work on `DAA`.
3. Each phase step starts in plan mode. Show Vishwa the plan, and write any new D-number before the code.
4. At the end: run the section 9.2 checks, update section 0, and report what ran and what didn't.

---

## 12. Open questions: ask Vishwa, do not decide alone

Settled: the frontend stack (D15); where the design HTML lives (`docs/design/`); JS/TS key detection depth for V1 (the Python AST; JS/TS and Dart by patterns + entropy; `tree-sitter` is revisited in V2); OAuth (not needed in V1, revisit in V2).

1. *(Settled 2026-10-25: the name stays **FlowForge**; the package is `flowforge-map` on PyPI and npm.)*
2. **Check timer (Phase 5).** Whether checks also run on a timer, and how often by default.
3. **Authenticated checks (Phase 5).** Should a health check ever call an endpoint that needs the user's key from `.env`, or only check reachability without one?
4. **GitHub URLs.** When the "scan a GitHub URL" input lands (Phase 4 or after).
5. **Antigravity (Phase 10).** Can it run headless, without its window? Check before relying on it.
6. **Dashboard housekeeping.** Delete `frontend/classic.html`? (The bundle is split per page now.)
7. **Flow advice grouping (Phase 6).** Advice groups calls that could start at the same moment (trip planner: {ip-api, Nominatim} and {the sight, Open-Meteo, fetch, currency}). The plan said the first four calls form one card. Keep the grouping by start time, or merge?
