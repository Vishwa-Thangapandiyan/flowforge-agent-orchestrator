# Contributing to FlowForge

Thanks for helping. FlowForge is small on purpose: one Python process, SQLite, files on disk. This page is everything you need to make a change that gets merged.

## Set up

```bash
uv sync              # Python ≥ 3.12; installs everything, including dev tools
uv run pytest        # the whole suite, offline: no API key, no network
uv run ruff check    # lint
```

Run the app with `uv run uvicorn flowforge.main:app --reload` and open http://localhost:8000.

## Before you open a pull request

1. `uv run pytest` passes offline, and `uv run ruff check` is clean. CI runs both on Linux and Windows.
2. New behaviour has tests, including at least one failure case.
3. The benchmarks still run: `uv run python benchmarks/run_benchmark.py sim --graphs 20 --k 4`.
4. A design change gets a new numbered entry in [DECISIONS.md](DECISIONS.md) (the next free D-number), written before the code. Existing decisions are superseded by new ones, never edited to mean something else.

## Rules that keep FlowForge safe and free

- **Tests never touch the network or need a key.** Use `mock` steps, stubbed clients, `httpx.MockTransport`, or an in-process MCP server (see `backend/tests/`).
- **Never put a real key anywhere**: not in code, tests, fixtures, docs or commits. Use obviously fake ones such as `sk_test_FAKEFAKE12345678`.
- **Connectors hold secret references, never values**: `env:NAME` today, `vault:NAME` once the vault ships.
- **Zero cost by default.** No paid service in the default install, the tests or CI. Paid providers are fine as optional connectors.
- **Don't change the five scheduling policies' behaviour** to make a feature easier; benchmarks compare them.
- **Timing in tests:** assert scheduling decisions (event order, which step started first), not wall-clock thresholds. Timer granularity and machine load vary too much across operating systems.
- Say "runs steps concurrently on one event loop", not "in parallel on CPUs".

## Branches

Work on a branch named `feat/<what>` and open a pull request into `main`. The `DAA` branch is the frozen course project: never commit to it or target it.

## Style

Match the code around you: type hints, `from __future__ import annotations`, short docstrings that cite decisions (`(D7)`), Pydantic models with `extra="forbid"`. Prefer the standard library and existing patterns over new abstractions; a new runtime dependency needs a reason in the pull request.
