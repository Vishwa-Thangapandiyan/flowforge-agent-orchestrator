# Trip planner (sample app for FlowForge)

A small app that plans a relaxed day trip. It uses only free services that need no key, so you can run it, scan it, and break nothing. FlowForge uses it three ways:
- the scanner's test case: the tables below are what a scan must find;
- the demo;
- the example map.

```bash
# from the FlowForge repo root, after `uv sync`
cd examples/trip-planner
../../.venv/bin/python planner.py Mangalore --to "Panambur Beach"
```

You need [Ollama](https://ollama.com) running with `llama3.1:8b` (`ollama pull llama3.1:8b`), plus `uvx` and `npx` for the MCP servers. Every call is tried on its own: a missing piece prints a ✗ and the plan goes on without it. A full run takes a minute or two on a laptop, mostly the local model.

It sends your IP address to ip-api.com (to guess your city) and the city name to OpenStreetMap, Open-Meteo, OSRM and Wikipedia. Nothing else leaves your machine.

## What it depends on (the scan must find these)

| Kind | Dependency | Evidence |
|---|---|---|
| LLM | Ollama, `llama3.1:8b`, through the OpenAI SDK | `services/llm.py:5`, `services/llm.py:14`, `config.py:11` |
| HTTP API | Nominatim (place → coordinates) | `config.py:15` |
| HTTP API | Open-Meteo (weather) | `config.py:16` |
| HTTP API | OSRM demo server (routes) | `config.py:17` |
| HTTP API | ip-api (your city from your IP) | `config.py:18` |
| HTTP API | Google Static Maps (a link it prints; never called by the app) | `config.py:24` |
| HTTP API | Wikipedia, fetched through the `fetch` MCP server | `planner.py:67` |
| MCP | `time` (`uvx mcp-server-time`, pinned) | `.mcp.json:3` |
| MCP | `fetch` (`uvx mcp-server-fetch`) | `.mcp.json:7` |
| MCP | `files` (`npx @modelcontextprotocol/server-filesystem`, pinned, only `trips/`) | `.mcp.json:11` |
| MCP | `currency` (a local Python server) | `.mcp.json:15` |
| Local | `tools/packing_list.py`, run as a subprocess | `planner.py:37` |

Env var names it reads: `OLLAMA_BASE_URL`, `PLANNER_MODEL` (`config.py:11-12`), and `CURRENCY_API_URL` (`mcp_servers/currency.py:9`).

These are libraries, not dependencies: `httpx`, `mcp`, `openai` (`requirements.txt`). They are the clients the app uses to reach the dependencies above.

## Planted problems (the checks must find these)

| What | Where | Found by |
|---|---|---|
| A hard-coded Google key (fake, `AIzaFAKE…`) | `config.py:23` | security findings (Phase 6) |
| A plain `http://` API | `config.py:18` (ip-api's free tier is http only) | security findings (Phase 6) |
| An unpinned MCP package | `.mcp.json:9` (`mcp-server-fetch`, no version) | security findings (Phase 6) |
| An MCP server that never starts | `currency`: exits with "CURRENCY_API_URL is not set" | health checks (Phase 5) |

The key is fake and never works. Never put a real key in this folder.
