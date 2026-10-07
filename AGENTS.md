# AGENTS.md

Instructions for any coding agent working in this repo (Claude Code, Codex, or others).

**`CLAUDE.md` is the rulebook. Read it in full first.** Its status block (section 0), security spec (section 6) and "Never" list (section 9.3) bind every agent below. This file adds only two things:

- **Part A:** the build workflow, meaning which agents build FlowForge, in what order, and how work moves between them.
- **Part B:** the runtime agents, meaning which processes are deployed and run when FlowForge is in production.

If this file and `CLAUDE.md` disagree, `CLAUDE.md` wins. Stop and tell Vishwa about the conflict.

---

# Part A — Build agents

## A1. Roster

Each agent has one job, a set of paths it may write, and a hand-off it must produce. An agent never writes outside its paths. If a change needs another area, it hands off to that area's agent.

| Agent | Job | May write | Must not | Hands off |
|---|---|---|---|---|
| **Lead** | Owns the phase: plan mode, talks to Vishwa, splits work, merges hand-offs, keeps the status block current | `CLAUDE.md` §0, `AGENTS.md`, branch/PR | Write feature code in `security/` or `scheduler/` alone | Approved plan → everyone |
| **Scout** (read-only) | Maps the code a task touches before anyone edits it | nothing | Edit any file | Facts as `file:line` + one line each; open questions |
| **Spec** | Writes new D-numbered entries in `DECISIONS.md` *before* code (`CLAUDE.md` §4) | `DECISIONS.md` | Renumber or silently change an existing decision | D-entry text for Lead to show Vishwa |
| **Test** | Writes failing tests first: offline, fake keys only, hypothesis where an invariant exists | `backend/tests/`, test fixtures | Use a network, a real key or a sleep-based flake | Red test list + the command that runs them |
| **Core** | Scheduler, schema, templating, storage, API routes | `scheduler/`, `schema.py`, `templating.py`, `storage.py`, `main.py` | Change any of the five policies' behaviour to suit a feature | Diff + `uv run pytest` output |
| **Connectors** | Node classes, connector registry, presets, MCP discovery, local command node | `nodes/`, `connectors/` | Hard-code a brand outside `connectors/presets.py`; use `shell=True` | Diff + tests with stubbed clients |
| **Security** | Vault, redaction, patterns, log filter, guards | `security/` | Add any route that returns a secret value | Diff + property/golden/leak test output |
| **Frontend** | Dashboard to the design spec in `docs/design/system-map.html` | `frontend/` | Invent a new look; keep a secret in state, URL or `localStorage` | Diff + screenshots (light, dark, phone width) |
| **Infra** | CI, ruff, packaging/CLI, Phase 5 queue, worker and deployment files | `.github/`, `pyproject.toml`, `deploy/`, `backend/flowforge/distributed/` | Add a paid service or a test that needs Redis/network by default | Diff + CI run result |
| **Reviewer** (fresh context) | Independent review against `CLAUDE.md` and the D-entries; correctness first | nothing (comments only) | Fix what it reviews | Findings, most severe first |
| **Security auditor** (fresh context) | Hunts leaks: route walk, DB/SSE/log/cache grep for fake keys, prompt contents, gitignore rules | nothing (comments only) | Approve its own fixes | Pass, or a blocking list. **Has veto on any phase touching secrets, LLM prompts, the network or the swap flow** |
| **Verifier** | Runs the definition of done (`CLAUDE.md` §9.2) and reports actual output | `CLAUDE.md` §0 status, README quickstart | Claim green without pasted output | DoD checklist with command output |

The **human gates** are Vishwa. Agents never pass them on their own.

## A2. The workflow for one phase (it is itself a DAG)

```
scout ─► lead: plan mode ─► [GATE: Vishwa approves plan]
                                   │
                                   ▼
                                 spec  (D-entries) ─► [GATE: Vishwa approves D-entries]
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
                test(area 1)   test(area 2)   test(area n)      ← independent, run side by side
                    │              │              │
                    ▼              ▼              ▼
                impl(area 1)   impl(area 2)   impl(area n)      ← side by side only if paths don't overlap
                    └──────────────┼──────────────┘
                                   ▼
                         ┌─────────┴─────────┐
                         ▼                   ▼
                      reviewer        security auditor            ← fresh context, side by side
                         └─────────┬─────────┘
                                   ▼
                        fix loop (max 2 rounds, back to the owning impl agent)
                                   ▼
                               verifier ─► lead: docs + status + PR ─► [GATE: Vishwa merges]
```

Rules:
1. **Plan mode first** for every phase and for anything touching `scheduler/`, `security/` or `schema.py`.
2. **Parallel only when write paths are disjoint.** Parallel implementers each work in their own git worktree on the phase branch. If two areas need the same file, they run one after the other.
3. **Tests before code** for `security/` and any new scheduler behaviour. The Test agent's red tests are the Implementer's acceptance criteria.
4. **Fix loop is bounded:** at most 2 rounds. After that the Lead takes the remaining findings to Vishwa instead of looping.
5. **Every hand-off is short and factual:** what changed (files), what was run (command plus real output), and what is still open. No "should work".
6. Branch per phase (`feat/phase-N-<name>`), small commits, PR into `main`. Never touch `DAA`.

## A3. Who works on each phase

| Phase | Lead plus these agents | Auditor required? |
|---|---|---|
| 1 Any LLM, any MCP | Scout, Spec (connector models), Test, **Connectors**, Core (`connector` field on `Step`, per-connector buckets), Infra (ruff, CI, CONTRIBUTING), Reviewer, Verifier | Yes, light (env/secret handling in LLM and MCP config) |
| 2 Dashboard v1 | Scout, Spec (frontend stack, after Vishwa answers §12.1), Test, **Frontend**, Core (persisted runs, `GET /runs`), Infra (console script), Reviewer, Verifier | Yes, light (no secret in the DOM) |
| 3 Connectors, secrets, security | Scout, Spec, Test (first and largest), **Security**, Connectors, Core (connector routes), Frontend (Views 2, 5, 6), Reviewer, Verifier | **Yes, full, with veto** |
| 4 Gates + swap | Scout, Spec (gate step), Test, **Core** (gate step), Security (redact → LLM → verify → scan → restore), Connectors (`local`), Frontend (View 3), Reviewer, Verifier | **Yes, full, with veto** |
| 4b AI-assisted tasks | Scout, Spec, Test (anti-hallucination, patch validation), Core (patch apply, versions), Connectors (fact sheet), Security (prompt contents), Frontend (View 7, once designed), Reviewer, Verifier | **Yes, full, with veto** |
| 5 Server + ROG workers | Scout, Spec (P1–P9 in `FlowForge_Server_Orchestrator_Plan.md`), Test, **Infra**, Core (`RemoteNode`), Security (worker vault, token auth), Frontend (workers in Tool health), Reviewer, Verifier | **Yes, full, with veto** |
| 6 Visual builder | Not planned yet | — |

## A4. Mapping to tools

The roles are tool-neutral. How to run them:

| Role | Claude Code | Codex |
|---|---|---|
| Lead | the main session, in plan mode | the main session |
| Scout | `Explore` subagent | read-only run |
| Reviewer, Security auditor | a fresh subagent (or `/code-review`, `/security-review`) with only the diff and `CLAUDE.md` | a fresh session given the diff |
| Implementers | subagents with `isolation: worktree` when running in parallel | separate sessions per worktree |
| Second opinion on a hard bug | `codex:rescue` | — |

Spawning agents costs context and money. Use a subagent only when the work is clearly independent or needs a fresh, unbiased context (review, audit). Small tasks stay in the Lead's session.

---

# Part B — Runtime agents (what gets deployed and run)

These are the long-running processes of FlowForge itself. Until Phase 5 everything is one process on one machine. The design is in `FlowForge_Server_Orchestrator_Plan.md`; this is the deployment checklist.

## B1. Today (Phases 1–4): one process, local

| Agent | Where | Start | Notes |
|---|---|---|---|
| `flowforge-core` | your machine | `uv run uvicorn flowforge.main:app --reload` (a `flowforge` console script is planned for Phase 2) | binds `127.0.0.1`; SQLite in `flowforge.db`; MCP servers it spawns over stdio are child processes, not separate agents |

## B2. Phase 5: control plane + workers (planned, not built)

| Agent | Machine | Runs as | Job | Must have |
|---|---|---|---|---|
| **`flowforge-core`** | Debian server | systemd service, restart on failure | API, dashboard, scheduler, caches, vault, `RemoteNode`, in-process worker for `core` placement (cloud LLMs, HTTP, fetch MCP, gates) | `FLOWFORGE_API_TOKEN` when not on localhost; binds the Tailscale IP only |
| **`redis`** | Debian server | systemd service | job streams, results, heartbeats (in-flight state only, safe to wipe) | bound to the Tailscale IP, `requirepass`, protected mode, never on the LAN or internet |
| **`flowforge-worker`** | ASUS ROG (Windows 11) | started at log-on (Task Scheduler) or by hand; native vs WSL2 is an open question | pulls jobs for its capabilities (Ollama/GPU, `local` commands, heavy MCP servers), heartbeats every 5 s, reports results | its own worker token, its own local vault for the secrets it needs, the same FlowForge version as the server |
| **`ollama`** | ASUS ROG | Ollama's own service | local model serving for `llm` connectors placed on the worker | listens on localhost only; the worker calls it, nothing else does |
| **`tailscaled`** | both | OS service | private network between the machines | an ACL allowing only the ROG and Vishwa's devices to reach the server's ports |

What is **not** a deployed agent: the AI planner (Phase 4b) and LLM steps. They are calls made by `flowforge-core` or a worker, scheduled like any other step, never processes with their own access.

## B3. Bring-up order and health checks

1. `tailscaled` on both, ACL applied → each machine can reach the other by its tailnet name.
2. `redis` on the server → `redis-cli -h <tailscale-ip> -a … ping` works from the ROG and fails from any other LAN device.
3. `flowforge-core` → the dashboard loads over the tailnet with the token and refuses without it.
4. `ollama` on the ROG → `ollama list` shows the model.
5. `flowforge-worker` on the ROG → registers, Tool health shows it green with its capabilities.
6. Smoke run: `diamond_mock.json` with one step placed on `worker` → it completes. Then close the lid mid-step → the step shows `waiting_for_worker` or retries, and finishes or dead-letters as `FlowForge_Server_Orchestrator_Plan.md` §4 says.

## B4. Runtime rules (from `CLAUDE.md`, restated because they bite here)
- No secret values on the queue. Workers resolve `secret_ref` from their own vault.
- Side-effecting steps without idempotency support stay on `core` and stay gated.
- Workers never call each other or external services on behalf of another worker. Hub and spoke.
- Nothing binds `0.0.0.0` without a token.
