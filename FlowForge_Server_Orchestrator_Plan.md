# FlowForge — Agent Orchestrator on the Home Server (V2 / Future Scope)

This is **not part of the V1 deliverable.** V1 stays single-machine and focused on proving the algorithms. This plan is what comes *after* V1 is working and benchmarked — a real two-machine deployment using hardware already owned: a Debian home server + an ASUS ROG.

---

## Why This Split Makes Sense (not overengineering)

The orchestrator's job is bookkeeping: hold the queue, track dependencies, know what's running and what's pending — all of which is cheap and needs to be reachable at all times. The ROG is a gaming laptop: it gets closed, moved, put to sleep, runs out of battery. If the orchestrator lived on the ROG, the whole system disappears the moment it's off.

Splitting them means:
- The server is always on, always reachable — you can submit/check jobs from anywhere.
- The ROG only needs to be on when you actually want heavy compute done; it shows up, grabs work, does it, and can disappear again.

This is the same pattern real infrastructure uses — Kubernetes' control plane vs. worker nodes, Ray's head node vs. worker nodes. Building a real, working version of it (not a simulation) is a legitimate step up from V1, not a distraction — **as long as it happens after V1 is solid**, since none of this is DAA-syllabus algorithm work; it's infrastructure on top of algorithms that already work.

---

## Architecture

```
   [You / frontend, anywhere]
              │
              ▼
   ┌─────────────────────────┐
   │  Debian home server        │   ← control plane (always on, 8GB is enough)
   │  - FastAPI                   │      - runs the scheduler (topo sort,
   │  - Scheduler (from V1)        │        critical path, cache — same code as V1)
   │  - Redis (job queue)            │      - pushes jobs to the queue, doesn't
   └──────────────┬───────────┘        do heavy compute itself
                  │ jobs on the queue
                  ▼
   ┌─────────────────────────┐
   │  ASUS ROG (worker)          │   ← connects when it's on
   │  - Worker script               │      - pulls jobs off the queue
   │  - Runs LLM (NIM)/MCP calls,     │      - does the actual heavy work
   │    local model inference, etc.    │      - reports results back
   └─────────────────────────┘
```

**Server = control plane.** Runs the same scheduler logic already built in V1 (topological sort, critical path, cache), plus a Redis queue. It decides *what* needs to happen and *in what order*, and puts jobs on the queue — it never does the heavy work itself.

**ROG = worker.** Runs a small worker script that connects to the same Redis instance over the home network, pulls jobs, executes them (LLM calls via NVIDIA NIM, MCP tool calls, or heavier local compute later), and reports results back.

---

## What Changes From V1

| V1 | This version |
|---|---|
| Everything on one machine | Split across two machines |
| Steps run as direct function calls | Steps become jobs on a Redis queue |
| One process does scheduling + execution | Server schedules, ROG executes |
| No networking concerns | Needs the two machines to reliably find each other |
| Worker is always "available" (it's the same process) | Worker (ROG) comes and goes — must be handled explicitly |

---

## Key Pieces to Build

1. **Redis job queue** on the server — steps from the scheduler get pushed here instead of called directly.
2. **Worker script** on the ROG — connects to Redis, pulls a job, runs the right node type (reuse the `nodes/` code from V1), pushes the result back.
3. **Networking (Tailscale)** — since the ROG won't always be on the same home network, set up Tailscale (free, simple) early so the two machines can always find each other securely, rather than fighting port-forwarding later.
4. **Retries + idempotency** — if the ROG drops mid-job (closed laptop, lost connection), the job should be retried safely, not silently lost or run twice.
5. **Distributed rate limiting** *(if calling a rate-limited API)* — track usage in Redis, not a local variable, so it's correct even with multiple workers later.
6. **Dead-letter handling** — a job that keeps failing gets set aside and flagged instead of blocking everything else.

---

## The Honest Selling Point

Because the ROG isn't always on, this setup forces real fault-tolerant, queue-based behavior — jobs wait for a worker, retries happen when one drops mid-task — instead of the easy fiction of "workers are always up." That's a genuine distributed-systems problem you'll have actually solved, on real hardware, not simulated across processes on one laptop. Good story for a viva or an interview, and a natural, honest V2 milestone once V1 is done.

---

## Sequencing Reminder

Don't start this until V1's algorithms (topological sort, critical path, caching, async execution) are fully working and benchmarked. This plan is explicitly the *next* milestone, not a parallel track — splitting effort across both at once risks neither one being solid.
