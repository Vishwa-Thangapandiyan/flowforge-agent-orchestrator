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

### Install

```bash
uvx flowforge-map --example      # try it: a sample app's maps in your browser, no keys, nothing sent
pipx install flowforge-map       # or install it (the command is `flowforge`)
flowforge --repo ~/my-app        # map your own repo
```

You need Python 3.12 or newer ([uv](https://docs.astral.sh/uv/) installs it for you). The dashboard is inside the package: no Node needed. Your data lives in `~/.flowforge`.

**Using pip?** Install inside a virtual environment (`python -m venv .venv && . .venv/bin/activate && pip install flowforge-map`). Many systems refuse a plain `pip install` outside one ("externally managed environment", PEP 668). `pipx` and `uvx` make that environment for you.

The first time, a short welcome walks you through three steps, each one skippable: your app's folder (or the example), pairing your coding agent once, and a lock for your keys. **⚙ Settings** at the bottom of the rail keeps what applies to every project: your agent, the theme and map style, the Vault's lock, and your data (each project's size, the MCP servers it may start, its check history, and the version, with **Check for updates**, which asks pypi.org only when you press it).

### Terminal

```bash
flowforge status [PROJECT]     # health, issues, missing keys and the next step
flowforge projects             # every project at a glance
flowforge issues [PROJECT]     # security findings and fixes
flowforge check [PROJECT]      # preview checks; run them from the dashboard
flowforge settings             # saved settings, data location and version
flowforge scan ~/my-app        # terminal summary; pipe it or use --json for JSON
flowforge key list             # key names and statuses, never values
```

Project commands use the current folder's project, else the last opened; PROJECT is its name or id. They read local files and work with the dashboard stopped. `--plain` or `NO_COLOR` disables colour and the banner; pipes have no colour or animation.

### Desktop app

The same dashboard in its own window, with Python inside: nothing else to install. Download the installer for your computer from the [Releases](https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/releases) page:

| Your computer | Download |
|---|---|
| Windows | `FlowForge_x.y.z_x64-setup.exe` or `.msi` |
| Mac (Apple Silicon or Intel) | `FlowForge_x.y.z_aarch64.dmg` or `_x64.dmg` |
| Linux | `.AppImage`, `.deb` or `.rpm` |

The builds aren't signed yet (signing costs money every year), so the first launch asks once:
- **Mac:** right-click FlowForge in Applications → **Open** → **Open**.
- **Windows:** on "Windows protected your PC", click **More info** → **Run anyway**.

After that it opens normally. **Browse…** picks your app's folder; **Settings → Your agent** pairs your coding agent with the app's own FlowForge.

### From source (to work on FlowForge)

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
uv run flowforge scan path/to/your/repo     # summary (pipe or --json for JSON); nothing stored, nothing sent
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

Switch the map to **Flow**. FlowForge reads your Python (by its syntax tree), Dart, JavaScript and TypeScript (by patterns, and says so), never running anything, and draws the order your code calls its dependencies: which call waits for which, the `if`s that choose, and where the code stops early. Every block and line points to its `file:line`.

- **The critical path** is the chain that sets the total time, weighted by the latencies your last check measured (LLMs are estimates, and say so).
- **Faster** compares "as written" (the slowest action, one call after another) with "could be", and lists the calls that don't need each other's results. **Show the change** writes out the `asyncio.gather`, Dart's `(a, b).wait` or `Promise.all` (now → could be, ready to copy) when it's safe; **Copy prompt for your coding agent** hands the rest to Claude Code, Codex or any agent. FlowForge never edits your code.
- **Watch it run** plays the could-be schedule; pointing at a block lights up its path. Five map styles: Studio, Boxed, Blueprint, Metro, Soft.


### Many projects

The home page lists every app you've mapped, with its dependencies, what needs fixing and missing keys. **+ New project** takes your app's folder, scans it and shows its map. The project tile at the top of the rail switches between the projects you have open, and each one comes back where you left it. **×** closes a project from that list without deleting it. Each project keeps its own map, checks, issues and keys; `flowforge --repo PATH` opens (or adds) that folder's project.

### Use it from your coding agent

FlowForge is also an **MCP server**, so Claude Code, Codex or Antigravity can ask it about your app and then make the change themselves. **Settings → Your agent** (also on **Connect agent**) gives you the one line (or config block) for your agent. With `uvx`, for Claude Code it looks like:

```bash
claude mcp add flowforge -- uvx flowforge-map mcp
```

Pair your agent once and it sees every project: `flowforge mcp` with no folder answers about the project your agent is working in, or any other by name (`list_projects` shows them all). Your agent gets eleven tools: `list_projects`, `get_map`, `get_flow`, `get_advice`, `check_health`, `get_security_findings`, `get_keys`, `get_fix_requests`, `request_key`, `wait_for_keys` and `what_changed`. All read only, except `request_key`, which only asks you for a key by name. Every answer is masked (key values never appear), the agent can't make FlowForge change your code, and a check starts an MCP server only after you said yes to it on the Checks page. FlowForge needs no AI of its own for any of this.

### Fix what's unsafe, with one click

The **Issues** page lists what the scan found unsafe, and every issue has one button:

| Issue | Button | What happens |
|---|---|---|
| A key written in Python, or in JS/TS that runs on Node | **Fix** | FlowForge shows the change (the key masked). On **Approve**, the key goes to your keys and the line reads it from the environment, on a new branch `flowforge/fix-…`. Your branch and files aren't touched; merge it when you're ready. |
| `http://`, an unpinned MCP server, a server given the whole disk, a key in `.mcp.json`, Dart or browser code | **Send to agent** | It joins your coding agent's list (`get_fix_requests`). Tell your agent "do the FlowForge fixes". |

Fix needs a git repo and the file committed. FlowForge works out the change itself, with no AI. Replace a key that was in your code with its provider anyway: older commits still hold it.

### Keys your coding agent never sees

**Add to code.** The **Keys** page lists each place your code needs a key, with its `file:line`. Paste the key and press **Add to code**:

```
lib/config.dart:8   String.fromEnvironment('SUPABASE_ANON_KEY')      ← FlowForge found the spot
[ •••••••••••• ]  [ Add to code ]                                      ← you paste, one click
✓ SUPABASE_ANON_KEY is in your app. Press Run as always.
  Changed: .flowforge/dart-defines.json · Run config · .gitignore · Claude Code told not to read it · Vault
```

The key goes where your app reads it, and **never into a code file**:

| Your app | The key goes to | Then |
|---|---|---|
| Flutter (`String.fromEnvironment`) | `.flowforge/dart-defines.json`, and `--dart-define-from-file` is added to your Run config (Android Studio, IntelliJ, VS Code) | press Run |
| Python, Node or Flutter with a `.env` loader | `.env` | start it as always |
| Vite | `.env.local` (as `VITE_…`) | start it as always |

- A placeholder like `apiKey = "ENTER KEY HERE"` is rewritten to read the key.
- A real key written in the code gets **Hide it**: one click moves it out the same way.
- The file is git-ignored, and nothing is committed: you see the change in `git diff`.
- An app that loads no file gets **Save**, and the Keys page says why.
- The settings a key needs come too: `SUPABASE_URL` is listed under **Your app also needs**, filled in from your Supabase key, with the same **Add to code** (a setting isn't secret, so it doesn't go to the Vault).

**With an agent**, the agent never gets a key; it gets a **mask**:

```
you paste STRIPE_SECRET_KEY once  →  your agent sees  ffkey://STRIPE_SECRET_KEY
the agent writes the mask where the key goes (or reads the env var STRIPE_SECRET_KEY in code)
the agent calls run_app(["flutter", "run", "--dart-define=STRIPE_SECRET_KEY=ffkey://STRIPE_SECRET_KEY"])
FlowForge asks you once: "Your agent wants to run flutter run … with STRIPE_SECRET_KEY"   [Deny] [Allow]
FlowForge (plain code, no AI) fills the mask and starts the app → the output comes back masked
```

Masks work in commands, in the environment and in `.env` lines; other config files never get the key written into them, so read the env var there. After you allow a command once, the same command runs without asking (**Settings** can turn the question off). The Keys page lists your agent's runs with **Stop**. This covers keys read when the app is *built* too, such as Flutter's `--dart-define` and Vite's `import.meta.env`. On the map, a 🔑 badge marks a block whose key is missing. With no keychain (a server, CI), keys go to an encrypted file in `~/.flowforge`.

**No agent?** The same works by hand:
```bash
flowforge key add STRIPE_SECRET_KEY        # typed hidden; saved in your OS keychain
flowforge key list                         # each key the code reads: saved · in .env · missing
flowforge run -- python app.py             # your app starts with the keys (masks filled)
```

**When your agent adds a dependency that needs a key**, it calls `request_key("STRIPE_SECRET_KEY", "for Stripe in pay.py")`. The map says "Your agent asked for a key", and the new block shows in coral, "key missing". Click it, paste the key on the Keys page, and the agent's `wait_for_keys` returns the moment it's saved. The agent only ever sees the name.

**See a key again** in the **Vault**: set a password and scan the QR with an authenticator app (Google Authenticator, Authy, 1Password), once. After that, your password, then the 6-digit code on your phone, open it for 5 minutes. It lists every key with its health: healthy, written in code, in `.env`, can't read, unused, or old. It also shows where each key lives, what uses it, and whether it's a live or test key. Each value shows for 30 seconds. Forgot the password? `flowforge lock reset --forget` drops the lock (your keys stay) and the dashboard says so.

What FlowForge promises: a key is never in anything your agent receives (answers, its own process, the output it returns), never in a code file, a stored row or a log. **Add to code** puts it in one hidden, git-ignored file next to your app (like `.env`), which Claude Code is told not to read; other agents could still read it. Outside FlowForge: what your own app does with a key, a key built into an app (anyone holding the app can read it, so use publishable keys there), and other programs running as your user. The 2FA on the Vault stops web pages, anyone at your browser, and anything without your phone.

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
| **Map** (home) | Your app's dependencies as blocks with a health dot; hover for `file:line`, click for details. The header has three controls: **⚠ N to fix** (keys in code, plain `http://`, risky MCP servers; values are never shown), **Check now**, and **⋯** (re-scan, scan another folder, your edits, export, legend, minimap, the five styles). **Flow** shows the order the code calls them, one action at a time, slowest first, with the **Faster** panel |
| **MCP Map** (Export) | The map to send: SVG, PNG, PDF, Mermaid or Flow JSON |
| **Checks** | Check now, each dependency's verdict, why it's down and the likely fix, and the history |
| **Connect agent** | The set-up for Claude Code, Codex or Antigravity; what your agent gets from this repo (dependencies, health, time, ways to be faster); and, once connected, what it asked |
| **Settings** (⚙, every project) | Your agent, paired once; the theme and the map style maps open in; the Vault's lock and where keys are kept (never a value); your data, each project's yeses and check history, and Check for updates |
| **How the Planner drew it** | The analysis replayed: read the repo, run the app in test mode, trace the calls, draft, check. What it read, what it dropped and why |
| **Re-check** | What changed in your repo since the last map: added, changed, removed, and conflicts with your edits. You pick what to take; the old version stays listed |
| **Apps and connectors** (Map ⋯) | A catalog of 56 apps with search and categories, honest **Live** / **Demo only** badges, and a mock test run for every one. Apps you connected but your code doesn't call wait here, off the map |
| **Connector page** | One app's connection (keys shown only as *configured*, *missing* or *example*), what it has done, and its recent activity |
| **Add an app** (from Apps and connectors) | LLM, MCP server, HTTP API or local command; colour and logo; a live preview; and exactly what gets saved, with no secrets |
| **Workflow runs** (under Checks, advanced) | Money and time saved, and every scheduled run: live bars with the slowest chain outlined, outputs, and why a failed run failed |

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
| 6b | Flow order from Dart and JS/TS | **Done** |
| 7 | Security findings: hard-coded keys, `http://` APIs, risky MCP configs | **Done** |
| 8 | Launch: docs, demo, `pip install` | Planned |
| 9 | CLI agent and a desktop app (Tauri) | Planned |
| 10 | V2: a local coding agent adds a dependency on a branch, for you to approve | Later |
| 11 | FlowForge's own small local model | Later |

The full roadmap with acceptance criteria is in [CLAUDE.md](CLAUDE.md) §5.

### Security

The scan looks for keys written in your code or MCP configs (**known key formats**, plus long random-looking values given to key-like names), APIs called over plain `http://`, and MCP servers with no pinned version or given the whole disk. It catches these patterns, not everything. A key's value is never stored, shown, logged or sent: findings hold the place, a masked excerpt and the fix. Test and fake-data files aren't searched.

FlowForge itself keeps keys out of its runs, events, cache, logs and the dashboard (known key formats and the keys you configured are masked), and the scan sends nothing to any LLM. Your own app's calls are outside FlowForge; for private code or data, a local model is the safe choice.

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
| `GET /security` | The scan's security findings, by level, with the fix and a prompt for each (D31) |
| `GET /projects`, `POST /projects`, `PATCH\|DELETE /projects/{id}`, `/p/{id}/…` | Every project; add a folder; rename or remove one (its folder is never touched); any route above for one project (D39) |
| `GET\|PATCH /settings`, `DELETE /projects/{id}/checks\|confirmed`, `POST /settings/update-check` | Settings for every project (no secret in them); clear a project's check history or take back its yeses; ask pypi.org for the newest version, only when pressed (D40) |
| `GET /keys`, `PUT /keys/{name}`, `DELETE /keys/{name}`, `POST /keys/{name}/import` | The keys the code reads and their status; save one (write-only), move one in from `.env`, or forget it (D36, D37) |
| `GET /issues`, `POST /issues/{id}/preview\|fix\|send` | Every issue with its button; the masked change; make it on a new branch; send it to your agent (D37) |
| `GET /lock`, `POST /lock/setup\|confirm\|password\|code\|close`, `GET /vault/keys`, `POST /keys/reveal` | The Vault: its lock (your password, then the authenticator code) and, once open, every key's health and one value at a time (D37, D38) |
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
| `backend/flowforge/flow/` | Flow order from code (Python by `ast`, Dart/JS/TS by patterns in `curly.py`): the calls, the `if`s, the critical path weights, the advice |
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

- [DECISIONS.md](DECISIONS.md): every design decision and its reason (D1–D9 for the scheduler core, D10–D18 for connectors, gates, MCP, local commands, planning, the dashboard, run history and the flow map, D19–D32 for the repo scan, health checks, flow order, the MCP Map, the MCP server for coding agents, security findings and Dart/JS flows)
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
