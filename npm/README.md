# FlowForge

**See everything your AI app depends on: whether it's reachable, whether it's safe, and what's slowing it down.**

```bash
npx flowforge-map
```

![The dependency map: every LLM, MCP server and API the app calls, with live health](https://raw.githubusercontent.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/main/docs/images/map.png)

| | |
|---|---|
| 🗺 **Map** | Every LLM, MCP server, HTTP API and local program your code calls, each with the `file:line` it came from |
| 💚 **Check now** | Green, amber or red for each one, with its latency. When something is down, it tells you why |
| ⚡ **Faster** | Reads the order your code makes its calls and shows which ones could run together, with the time you'd save |
| 🛡 **Issues** | Keys written in code, plain `http://`, MCP servers that aren't pinned. Fix one on a new branch, or send it to your agent |
| 🔑 **Keys** | Paste a key once. **Add to code** writes it to a git-ignored file your app reads; FlowForge only ever hands your agent a mask |
| 🤖 **Your agent** | Claude Code, Codex and Antigravity can read the map, the advice and the issues |

![Flow: 16.5 s as written, 11.6 s if four calls start together](https://raw.githubusercontent.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/main/docs/images/flow.png)

![Issues: a key in the code, an unpinned MCP server, plain http](https://raw.githubusercontent.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/main/docs/images/issues.png)

Free and open source (MIT) · runs on your machine · the scan sends nothing to any LLM
