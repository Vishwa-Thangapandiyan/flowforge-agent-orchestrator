# FlowForge — Server + ROG Workers (Phase 7 plan)

This is **Phase 7** of the roadmap in `CLAUDE.md` (section 5). It turns the single-process FlowForge core into a control plane on the Debian home server plus workers on the ASUS ROG, connected over Tailscale.

**Do not start this before Phase 4 (vault, redaction, guards) is done.** Distributing work across machines means secrets and step outputs travel over a network. The security spec in `CLAUDE.md` section 6 has to exist before that happens, not after.

The runtime processes this plan deploys are listed in `AGENTS.md` (Part B). The decisions below are **proposals**. Each becomes a D-numbered entry in `DECISIONS.md` (the next free numbers at the time they are written) and is approved by Vishwa *before* any code is written.

---

## 1. Why split it (and why it isn't overengineering)

The control plane does bookkeeping: it holds the DAG, the ready heap, the caches, the vault and the run history. That work is cheap but must always be reachable. The ROG is a laptop. It gets closed, sleeps, moves between networks and runs out of battery. If the control plane lived on it, the whole system would disappear whenever the lid closed.

- **Server (always on):** accepts runs, schedules them, serves the dashboard, and keeps state. It never does heavy compute.
- **ROG (comes and goes):** shows up, pulls the jobs it can do (local models, GPU work, local commands), does them, and can leave again.

This is the same split as Kubernetes' control plane vs worker nodes, or Ray's head node vs workers. The honest selling point is that because the worker really does disappear, the system *has* to handle jobs that wait, leases that expire and retries after a mid-job drop, on real hardware rather than simulated processes on one laptop.

---

## 2. Target architecture

Hub and spoke stays the rule (`CLAUDE.md` section 3): **nothing talks to anything directly; every call goes through FlowForge core.** Workers are just another spoke.

```
        dashboard (any device on the tailnet)
                     │  HTTPS + token  (SSE events, REST)
                     ▼
┌──────────── Debian server: control plane ─────────────────────────────┐
│ flowforge-core (FastAPI, one process)                                  │
│   scheduler: Kahn, critical path, HLFET, 5 policies   ← unchanged      │
│   rate-limit buckets + caches + vault + redaction      ← unchanged     │
│   RemoteNode: Node.run(params) → job on queue → await result   ← NEW   │
│   storage: SQLite (runs, durations, cache, connectors, workers)        │
│   in-process worker for cloud-API steps (NIM, HTTP, fetch MCP)         │
│ redis  (bound to the Tailscale IP only, password on)                   │
└───────────────┬───────────────────────────────────────────────────────┘
                │ Tailscale (WireGuard), Redis Streams
                ▼
┌──────────── ASUS ROG (Windows 11): worker ────────────────────────────┐
│ flowforge-worker                                                       │
│   heartbeat + capabilities (gpu, ollama, local commands, mcp servers)  │
│   pulls jobs for its capabilities → runs the existing Node classes     │
│   reports result / error / progress back                               │
│   Ollama, Sirius, local scripts, heavy MCP servers                     │
└───────────────────────────────────────────────────────────────────────┘
```

### The key design move: the scheduler doesn't change

The executor already calls `node.run(params)` after taking a rate-limit token and inside `asyncio.wait_for` (`scheduler/executor.py`). Phase 7 adds one Node, **`RemoteNode`**, which implements `run` by:

1. publishing a job `{job_id, run_id, step_id, attempt, connector_id, params (redacted, resolved), deadline}` to the queue for that connector's placement,
2. awaiting the result on a per-job reply channel,
3. mapping outcomes onto the errors the executor already understands:
   - worker error marked transient, lease expired, worker lost → `TransientNodeError` (so the existing retry with full jitter and a fresh token applies),
   - permanent worker error → `NodeError`,
   - `asyncio.wait_for` cancellation → publish a cancel for that `job_id`.

As a result, the five policies, the critical-path DP, the caches, the retries, the skip-on-failure handling and the SSE events all keep working unchanged, and the benchmarks keep running. `CLAUDE.md` section 4 requires this.

### What stays on the server vs what goes to the ROG

| Step / connector | Runs on | Why |
|---|---|---|
| `llm` on cloud providers (NIM, Gemini, Claude) | server (in-process) | I/O-bound, needs a vault secret, no benefit from the GPU |
| `http`, `fetch` MCP | server | I/O-bound, cheap |
| `gate` | server | waits on a human; never a job |
| `llm` on Ollama / local models | ROG | needs the GPU |
| `local` (Sirius, scripts) | ROG | the files and tools live there |
| MCP servers marked heavy | ROG | CPU/GPU or local files |
| `mock` | wherever the test/benchmark says | used to simulate worker latency and dropout |

Placement is a connector setting: `placement: "core" | "worker" | "worker:<name>"` (default `core`, so every existing workflow and connector behaves exactly as today).

---

## 3. Proposed decisions (write as D-entries first)

### P1. Queue: Redis Streams with consumer groups and leases
- One stream per placement (`ff:jobs:core`, `ff:jobs:worker`, `ff:jobs:worker:rog`). Workers read with `XREADGROUP`, acknowledge with `XACK` only after the result is stored.
- **Lease:** a job that has been pending longer than its lease (default: the step's `timeout_s` + 10 s) is reclaimed with `XAUTOCLAIM` and counted as a lost attempt (`TransientNodeError` → normal retry path).
- Results go to `ff:result:<job_id>` (a short-lived key) plus a notification. The control plane accepts a result only if its `(job_id, attempt)` is the current attempt. **Late results from a timed-out or reclaimed attempt are dropped and logged**, never applied.
- A `Queue` protocol with two implementations: `InMemoryQueue` (tests, single-machine, default) and `RedisQueue`. **Tests use the in-memory one and never need Redis or a network** (`CLAUDE.md` 9.3). Redis integration tests are opt-in (`-m redis`) and skipped by default.

### P2. Delivery is at-least-once, so side effects need idempotency keys
A worker can finish a job and lose its connection before acknowledging it. The job then runs again. That is fine for reads and LLM calls but not for payments or writes.
- Every job carries `idempotency_key = sha256(run_id, step_id)` (stable across attempts).
- Nodes that talk to APIs with idempotency support (Stripe's `Idempotency-Key`, and similar) pass it through.
- Steps with `side_effects: true` and no idempotency support are **pinned to `core`** and still sit behind a gate (`CLAUDE.md` 6.5). Phase 7 does not weaken any gate.

### P3. Rate limiting stays central
Tokens are taken by the executor on the control plane *before* `node.run`, so with one control plane the existing in-process buckets remain correct for any number of workers. A Redis-backed bucket (a Lua script, atomic refill and take) is only needed if a second control plane is added later, and is out of scope until then. (This corrects the earlier version of this plan, which assumed Redis rate limiting was required from the start.)

### P4. Secrets never ride the queue
- Job params are the **redacted, resolved** params, the same form already stored in caches and events.
- A worker that needs a secret (e.g. an MCP server env key on the ROG) gets it from **its own local vault** (`FLOWFORGE_HOME/vault.db` on the ROG, its own master key), keyed by the same `secret_ref`. The server never sends values.
- If the worker's vault lacks the secret, the job fails permanently with `missing secret <secret_id>` (no value, no length), and the dashboard shows the connector as `missing` on that worker.
- Results are run through `redact` + `scan` on the worker *and again* on the server before storage or SSE. An output that fails `scan` is never cached.

### P5. Worker membership and health
- Worker registers with `{name, version, capabilities, capacity}`. Heartbeat every 5 s to `ff:workers:<name>` with a 20 s TTL.
- **Version check:** a worker with a different FlowForge version from the server, or a different node protocol version, is refused with a clear message. No silent mismatch.
- Missing heartbeat → `worker_lost` event. Its in-flight jobs are reclaimed at lease expiry, not instantly (a laptop waking from sleep may still finish).
- Capacity: the worker never holds more than `capacity` jobs (default = CPU count for `local`, 1 for GPU work). The executor's global `k` is unchanged.
- **No worker online for a placement:** the step stays `running` with a `waiting_for_worker` event. Optional `worker_wait_timeout_s` on the connector turns a long wait into a failure. The default is to wait, because a closed laptop is normal.

### P6. Dead-letter
After the step's `retries` are exhausted on transient causes, the job goes to `ff:dead` with its last error. The step fails (descendants are `skipped`, as in D7), and the dashboard shows it under Controls with **Retry** and **Discard**. Dead-lettered jobs never block other runs.

### P7. Durations measure work, not waiting
The EWMA history (D1) must not learn queue wait time as step cost, because that would distort the critical path every time the laptop is closed. The worker reports its own execution time. `RemoteNode` records it as the step's measured duration, and the queue wait is reported separately in the event (`queued_ms`).

### P8. Network and auth
- Tailscale on both machines. Tailscale ACL: only the ROG and Vishwa's devices can reach the server's Redis and API ports.
- Redis binds to the server's Tailscale IP only, `requirepass` set, protected mode on. It is never exposed on the LAN or the internet.
- `flowforge-core` binds `127.0.0.1` by default. Binding to the Tailscale IP or `0.0.0.0` **requires** `FLOWFORGE_API_TOKEN`, checked on every route and on the SSE stream (`CLAUDE.md` 6.5). Workers authenticate with their own token, not the dashboard's.
- No multi-user accounts (single-user rule still applies).

### P9. Storage ladder
SQLite on the server remains the source of truth. Redis holds only in-flight traffic (jobs, results, heartbeats) and can be wiped without losing history. Postgres is the next step only when teams arrive, not part of Phase 7.

---

## 4. Failure modes and what happens

| Failure | Detection | Outcome |
|---|---|---|
| Laptop closed mid-job | heartbeat TTL + lease expiry | attempt counted lost → retry (fresh token, backoff) → dead-letter if retries exhausted |
| Laptop wakes and finishes a reclaimed job | `(job_id, attempt)` is stale | result dropped, `late_result_dropped` event |
| Same job delivered twice | idempotency key | external API dedupes; side-effecting non-idempotent steps never leave `core` |
| No worker online | no consumer for the stream | `waiting_for_worker`; optional timeout |
| Redis restarts | connection error in `RemoteNode` | `TransientNodeError` → retry; history safe in SQLite |
| Server restarts | — | runs in flight are marked `failed (interrupted)` on startup; open gates persist (D11). Resuming runs is **out of scope** for Phase 7 |
| Worker version mismatch | registration check | worker refused, dashboard shows why |
| Secret missing on worker | worker vault lookup | permanent `NodeError`, connector shows `missing` on that worker |

---

## 5. Milestones (one branch `feat/phase-6-<name>` each)

| # | Milestone | Acceptance (offline unless marked) |
|---|---|---|
| 6.1 | D-entries P1–P9 written and approved | Vishwa says yes |
| 6.2 | `Queue` protocol + `InMemoryQueue` + `RemoteNode` + in-process worker | All existing tests and benchmarks pass unchanged. A workflow with every step routed through `RemoteNode` + `InMemoryQueue` gives the same results and the same step order as direct nodes under all five policies (property test) |
| 6.3 | Leases, stale-result rejection, dead-letter | Tests: a worker that "sleeps" past its lease gets its job retried, and its late result is dropped; exhausted retries dead-letter and skip descendants |
| 6.4 | `flowforge-worker` CLI, registration, heartbeats, capabilities, version check | Two in-memory workers with different capabilities each receive only their jobs; a lost heartbeat produces `worker_lost` |
| 6.5 | `RedisQueue` + token auth + bind rules | `-m redis` tests (opt-in) pass against a local Redis; route walk confirms every route rejects a missing token when bound off-localhost |
| 6.6 | Real deployment: systemd units on Debian, ROG worker start-up, Tailscale ACL | **Manual, on hardware:** close the ROG lid during an Ollama step → job retried after wake or dead-lettered; dashboard Tool health shows the worker going grey and back to green |
| 6.7 | Dashboard: workers in Tool health, `queued_ms` in Money and time, dead-letter list in Controls | Component tests; scannable per `CLAUDE.md` UI principle |
| 6.8 | Benchmark: simulated worker dropout track | `sim` gains `--dropout p`; the five policies are unchanged; report makespan vs dropout rate |

Security work in every milestone follows `CLAUDE.md` 6.6: the leak test is extended so a fake key is grepped across the Redis stream contents, worker logs and the worker's result payloads, with zero hits expected.

---

## 6. Open questions for Vishwa (do not decide alone)

1. **Worker on Windows:** run `flowforge-worker` natively on Windows 11 (Task Scheduler at log-on), or inside WSL2? Native is simpler; WSL2 matches the server's Linux.
2. **Server also a worker?** Proposal: yes, the in-process worker handles `core` placement. Confirm that cloud LLM calls should never be routed to the ROG.
3. **Redis vs a simpler first queue:** Redis Streams is proposed. The alternative is a SQLite-backed job table polled over the API (no Redis at all), which is slower but has one less service. Pick before 6.5.
4. **Interrupted runs:** is "mark failed on server restart" acceptable for Phase 7, with resume deferred?
5. **Ollama placement:** is Ollama only ever on the ROG, or also on the server (CPU-only, slow) as a fallback connector?
