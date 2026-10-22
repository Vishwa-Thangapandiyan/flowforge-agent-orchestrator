import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";

afterEach(() => vi.unstubAllGlobals());

const CONNECT = {
  repo: "/home/me/trip-planner",
  command: ["/usr/bin/uv", "--directory", "/home/me/flowforge", "run", "flowforge", "mcp", "--repo", "/home/me/trip-planner", "--db", "/home/me/flowforge/flowforge.db"],
  agents: {
    claude: { name: "Claude Code", how: "terminal", checked: true, text: "claude mcp add flowforge -- /usr/bin/uv --directory /home/me/flowforge run flowforge mcp --repo /home/me/trip-planner" },
    codex: { name: "Codex", how: "terminal", checked: true, text: "codex mcp add flowforge -- /usr/bin/uv run flowforge mcp",
      file: "~/.codex/config.toml", file_text: "[mcp_servers.flowforge]\ncommand = \"/usr/bin/uv\"" },
    antigravity: { name: "Antigravity", how: "file", checked: false, file: "mcp_config.json (… menu → MCP Servers → Manage MCP Servers → View raw config)",
      text: "{\n  \"mcpServers\": {}\n}" },
  },
  last_call: null as null | { tool: string; repo: string; at: string },
};

test("each agent gets its set-up to copy, and the page says when the agent last called", async () => {
  const copied: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { copied.push(t); } } });
  mockApi({ "/meta": META, "/agent/connect": CONNECT });
  renderAt("/connect");
  expect(await screen.findByRole("heading", { level: 1, name: "Connect your coding agent" })).toBeInTheDocument();
  expect(screen.getByText(/No agent has called yet/)).toBeInTheDocument();
  // Claude Code first: one line for the terminal
  expect(screen.getByRole("tab", { name: "Claude Code" })).toHaveAttribute("aria-selected", "true");
  const panel = screen.getByRole("tabpanel");
  expect(panel).toHaveTextContent("claude mcp add flowforge --");
  await userEvent.click(within(panel).getByRole("button", { name: /Copy/ }));
  expect(copied[0]).toBe(CONNECT.agents.claude.text);
  expect(await screen.findByText("Copied")).toBeInTheDocument();
  // Codex: the line, or the same in its config file
  await userEvent.click(screen.getByRole("tab", { name: "Codex" }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("codex mcp add flowforge --");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("~/.codex/config.toml");
  // Antigravity: a file, and an honest note that its place differs between versions
  await userEvent.click(screen.getByRole("tab", { name: "Antigravity" }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent(/differs between versions/);
  // the five tools, read-only
  for (const tool of ["get_map", "get_flow", "get_advice", "check_health", "what_changed"]) {
    expect(screen.getByText(tool)).toBeInTheDocument();
  }
});

test("a call from the agent shows as proof the connection works", async () => {
  mockApi({ "/meta": META, "/agent/connect": { ...CONNECT, last_call: { tool: "get_advice", repo: "trip-planner", at: new Date().toISOString() } } });
  renderAt("/connect");
  expect(await screen.findByText(/Connected/)).toBeInTheDocument();
  expect(screen.getByText(/get_advice/, { selector: ".ca-last *" })).toBeInTheDocument();
});

test("the rail has a way in", async () => {
  mockApi({ "/meta": META, "/agent/connect": CONNECT });
  renderAt("/connect");
  expect(await screen.findByRole("link", { name: /Connect agent/ })).toHaveAttribute("href", "/connect");
});
