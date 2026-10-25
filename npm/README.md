# FlowForge

**See everything your AI app depends on: whether it's up, whether it's safe, and what's slowing it down.**

```bash
npx flowforge-map --example
```

One command opens a sample app's map in your browser. You don't need keys or sign-ups, and nothing about your code is sent anywhere.

![The dependency map: every LLM, MCP server and API the app calls, with live health](https://raw.githubusercontent.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/main/docs/images/map.png)

## Point it at your repo

```bash
npx flowforge-map --repo .
```

| | |
|---|---|
| 🗺 **Map** | Every LLM, MCP server, HTTP API and local program your code calls, each with the `file:line` it came from |
| 💚 **Check now** | Green, amber or red for each one, with its latency. When something is down, it tells you why |
| ⚡ **Faster** | Reads the order your code makes its calls and shows which ones could run together, with the time you'd save |
| 🛡 **Issues** | Keys written in code, plain `http://`, MCP servers that aren't pinned. Fix one on a new branch, or send it to your agent |
| 🔑 **Keys** | Paste a key once. **Add to code** puts it where your app reads it, and your coding agent only ever sees a mask |

![Flow: 16.5 s as written, 11.6 s if four calls start together](https://raw.githubusercontent.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/main/docs/images/flow.png)

## Works with your coding agent

Add FlowForge to Claude Code, Codex or Antigravity with one entry:

```json
{ "command": "npx", "args": ["-y", "flowforge-map", "mcp"] }
```

Your agent can then ask for the map, the advice and the issues, and run your app with keys it never sees.

![Issues: a key in the code, an unpinned MCP server, plain http](https://raw.githubusercontent.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator/main/docs/images/issues.png)

## Free, local, private

- **Free and open source (MIT).** No account and no paid service.
- **Local.** Everything stays on your machine, in `~/.flowforge`.
- **The scan is plain code.** It sends nothing to any LLM.
- **Desktop app** for Windows, macOS (Apple chips) and Linux, if you'd rather click than type.

**[Source, docs and the desktop app on GitHub →](https://github.com/Vishwa-Thangapandiyan/flowforge-agent-orchestrator)**
