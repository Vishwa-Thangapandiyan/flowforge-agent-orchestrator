# FlowForge

A DAG workflow scheduler for LLM / MCP / HTTP steps, built as a DAA project. It uses topological sort, critical-path DP, critical-path list scheduling under concurrency and rate limits, and memoization.

- Plan: [FlowForge_V1_Plan.md](FlowForge_V1_Plan.md)
- Design decisions: [DECISIONS.md](DECISIONS.md)
- Future scope (V2, two machines): [FlowForge_Server_Orchestrator_Plan.md](FlowForge_Server_Orchestrator_Plan.md)

## Setup (everything is free)

```bash
uv sync                      # installs deps + dev tools into .venv
cp .env.example .env         # add your free NVIDIA_API_KEY from build.nvidia.com
uv run pytest                # tests never hit the network
uv run uvicorn flowforge.main:app --reload
```

## Status

| Module | Owner | State |
|---|---|---|
| `schema.py`, `templating.py`, `storage.py`, `nodes/base.py`, `nodes/mock_node.py` | — | done |
| `scheduler/graph.py` | A | done — unit + property tests |
| `scheduler/critical_path.py`, `durations.py` | A | stub + contract tests in `tests/test_critical_path.py` |
| `scheduler/executor.py`, `rate_limit.py`, `cache.py` | B | stub |
| `nodes/llm_node.py`, `http_node.py`, `mcp_node.py`, `main.py`, `frontend/`, `benchmarks/` | C | stub |

Every stub's docstring states exactly what it must do.
