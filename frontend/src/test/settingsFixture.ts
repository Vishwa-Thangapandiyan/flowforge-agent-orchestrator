// What GET /settings answers (D40), for the Settings and welcome tests.
const AGENTS = {
  claude: { name: "Claude Code", how: "terminal", checked: true, text: "claude mcp add flowforge -- uvx flowforge-map==0.3.0 mcp" },
  codex: { name: "Codex", how: "terminal", checked: true, text: "codex mcp add flowforge -- uvx flowforge-map==0.3.0 mcp" },
  antigravity: { name: "Antigravity", how: "file", checked: false, file: "mcp_config.json", text: "{}" },
};
export const SETTINGS = {
  welcome_done: true, approve_runs: true, map_style: null, version: "0.3.0", install: "uvx", home: "/home/me/.flowforge", total_bytes: 3_500_000,
  projects: [
    { id: "shop", name: "shop", path: "/home/me/shop", size_bytes: 1_200_000, confirmed: ["uvx mcp-server-time"], checks: 12 },
    { id: "blog", name: "My blog", path: "/home/me/blog", size_bytes: 40_000, confirmed: [], checks: 0 },
  ],
  agent: { connected: true, last_call: { tool: "get_map", repo: "shop", at: new Date().toISOString(), got: "12 dependencies" },
    command: ["uvx", "flowforge-map==0.3.0", "mcp"], agents: AGENTS },
  vault: { lock: "on", store: "keychain" },
};

