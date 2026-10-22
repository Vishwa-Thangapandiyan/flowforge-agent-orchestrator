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
  last_call: null as null | { tool: string; repo: string; at: string; got: string },
  calls: [] as { tool: string; repo: string; at: string; got: string }[],
};

const PREVIEW = {
  repo: "trip-planner",
  cards: [
    { tool: "get_map", headline: "11 dependencies", sub: "1 LLM · 4 MCP servers · 6 APIs", tone: "plain" },
    { tool: "check_health", headline: "9 up · 1 down", sub: "10 last checks stored", tone: "bad" },
    { tool: "get_flow", headline: "16.5 s → 11.6 s", sub: "as written → could be", tone: "plain" },
    { tool: "get_advice", headline: "3 ways to be faster", sub: "saves ~2.2 s, the change written out", tone: "warn" },
    { tool: "what_changed", headline: null, sub: "After your agent edits: what it added or removed", tone: "plain" },
  ],
};

test("each agent gets its set-up to copy, and the page says when the agent last called", async () => {
  const copied: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { copied.push(t); } } });
  mockApi({ "/meta": META, "/agent/connect": CONNECT, "/agent/preview": PREVIEW });
  renderAt("/connect");
  expect(await screen.findByRole("heading", { level: 1, name: "Connect your coding agent" })).toBeInTheDocument();
  expect(screen.getByText(/Waiting for your agent's first question/)).toBeInTheDocument();
  // Claude Code first: one line for the terminal
  expect(screen.getByRole("tab", { name: /Claude Code/ })).toHaveAttribute("aria-selected", "true");
  const panel = screen.getByRole("tabpanel");
  expect(panel).toHaveTextContent("claude mcp add flowforge --");
  await userEvent.click(within(panel).getByRole("button", { name: /Copy set-up command/ }));
  expect(copied[0]).toBe(CONNECT.agents.claude.text);
  expect(await screen.findByText("Copied")).toBeInTheDocument();
  // Codex: the line, or the same in its config file
  await userEvent.click(screen.getByRole("tab", { name: /Codex/ }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("codex mcp add flowforge --");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("~/.codex/config.toml");
  // Antigravity: a file, and an honest note that its place differs between versions
  await userEvent.click(screen.getByRole("tab", { name: /Antigravity/ }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent(/differs between versions/);
});

test("before any call, the page shows what each tool would answer for this repo", async () => {
  mockApi({ "/meta": META, "/agent/connect": CONNECT, "/agent/preview": PREVIEW });
  renderAt("/connect");
  const gets = await screen.findByRole("region", { name: /What your agent gets from trip-planner/ });
  for (const tool of ["get_map", "get_flow", "get_advice", "check_health", "what_changed"]) {
    expect(within(gets).getByText(tool)).toBeInTheDocument();
  }
  expect(within(gets).getByText("9 up · 1 down")).toBeInTheDocument();
  expect(within(gets).getByText("Is anything down?")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: /What your agent asked/ })).not.toBeInTheDocument();
});

test("after the agent calls, the page says connected and lists what it asked, newest first", async () => {
  const at = new Date().toISOString();
  const calls = [{ tool: "get_advice", repo: "trip-planner", at, got: "3 ways to be faster · saves ~2.2 s" },
    { tool: "get_map", repo: "trip-planner", at, got: "11 dependencies" }];
  mockApi({ "/meta": META, "/agent/connect": { ...CONNECT, last_call: calls[0], calls }, "/agent/preview": PREVIEW });
  renderAt("/connect");
  expect(await screen.findByText("Connected")).toBeInTheDocument();
  const asked = screen.getByRole("region", { name: /What your agent asked/ });
  const rows = within(asked).getAllByRole("listitem");
  expect(rows.map((r) => r.textContent)).toEqual([
    expect.stringContaining("get_advice3 ways to be faster · saves ~2.2 s"), expect.stringContaining("get_map11 dependencies")]);
});

test("the rail has a way in", async () => {
  mockApi({ "/meta": META, "/agent/connect": CONNECT, "/agent/preview": PREVIEW });
  renderAt("/connect");
  expect(await screen.findByRole("link", { name: /Connect agent/ })).toHaveAttribute("href", "/connect");
});
