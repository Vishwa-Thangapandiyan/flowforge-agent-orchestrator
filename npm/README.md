# flowforge-map

**FlowForge** maps what your app depends on (LLMs, MCP servers, HTTP APIs, local programs) with the `file:line`
each comes from, checks that each is healthy and safe, and keeps your API keys away from your coding agent.

```bash
npx flowforge-map --example      # try it on a sample app: no keys, nothing sent
npx flowforge-map --repo .       # map the folder you're in
npx flowforge-map mcp            # the MCP server for Claude Code, Codex and other agents
```

No Python and no virtual env: the first run downloads FlowForge's ready-made program for your computer from the
project's GitHub Release, checks it against the release's `SHA256SUMS`, keeps it in `~/.flowforge/bin/<version>`,
and runs it. Later runs start at once, even offline. Windows, macOS (Apple and Intel) and Linux x64; elsewhere it
runs `uvx flowforge-map` instead.

Docs, source and the desktop app: https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator
