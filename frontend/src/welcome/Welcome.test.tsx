import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { META, mockApi, renderHome } from "../test/api";
import { DEPS } from "../test/flowFixture";
import { SETTINGS } from "../test/settingsFixture";

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const EMPTY: { default: string | null; example: { id: string; name: string }; projects: object[] } = { default: null, example: { id: "example", name: "Example: trip planner" }, projects: [] };
const SHOP = { id: "shop", name: "shop", path: "/home/me/shop", added: "2026-10-24T10:00:00Z", opened: null, missing: false,
  summary: { dependencies: 2, issues: 0, keys_missing: 0 } };

function firstLaunch({ connected = false, lock = "none", done = false } = {}) {
  let agentCalled = connected;
  const state = { projects: EMPTY, done };
  const calls = mockApi({
    "/projects": (init?: RequestInit) => {
      if (init?.method === "POST") { state.projects = { ...EMPTY, default: "shop", projects: [SHOP] }; return SHOP; }
      return state.projects;
    },
    "/settings": (init?: RequestInit) => {
      if (init?.method === "PATCH") { state.done = true; return { welcome_done: true, map_style: null }; }
      return { ...SETTINGS, welcome_done: state.done, projects: [],
        agent: { ...SETTINGS.agent, connected: agentCalled, last_call: agentCalled ? SETTINGS.agent.last_call : null } };
    },
    "/lock": { state: lock, open: false, seconds_left: 0, reset_at: null },
    "/meta": META, "/flow": DEPS, "/connectors": [], "/security": { findings: [] },
    "/issues": { repo: "shop", example: false, summary: {}, issues: [] }, "/keys": { repo: "shop", example: false, summary: {}, keys: [] },
    "/projects/shop/open": { id: "shop", opened: true },
  });
  return { calls, agentCalls: () => { agentCalled = true; } };
}

test("the first launch welcomes you: your app, your agent, your keys, then the app's map", async () => {
  const { calls } = firstLaunch({ connected: true, lock: "on" });
  renderHome();
  expect(await screen.findByRole("dialog", { name: "Welcome to FlowForge" })).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Step 1 of 3" })).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Your app's folder"), "/home/me/shop");
  await userEvent.click(screen.getByRole("button", { name: /Map it/ }));
  expect(await screen.findByRole("list", { name: "Step 2 of 3" })).toBeInTheDocument();
  expect(JSON.parse(String(calls.find((c) => c.url === "/projects" && c.init?.method === "POST")?.init?.body))).toEqual({ path: "/home/me/shop" });
  expect(await screen.findByRole("region", { name: "Your agent" })).toHaveTextContent("Connected");
  await userEvent.click(screen.getByRole("button", { name: /^Next/ }));
  expect(await screen.findByText("Your lock is already set.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Finish/ }));
  const patch = calls.find((c) => c.url === "/settings" && c.init?.method === "PATCH");
  expect(JSON.parse(String(patch?.init?.body))).toEqual({ welcome_done: true });
  expect(await screen.findByRole("link", { name: "Map" })).toHaveAttribute("aria-current", "page");   // shop's map
  expect(screen.getByRole("link", { name: "Map" })).toHaveAttribute("href", "/p/shop");
  expect(screen.queryByRole("dialog", { name: "Welcome to FlowForge" })).not.toBeInTheDocument();
});

test("skipping marks the welcome done and shows the home page", async () => {
  const { calls } = firstLaunch();
  renderHome();
  await userEvent.click(await screen.findByRole("button", { name: /Skip for now/ }));
  expect(calls.some((c) => c.url === "/settings" && c.init?.method === "PATCH")).toBe(true);
  expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "Welcome to FlowForge" })).not.toBeInTheDocument();
});

test("the agent step says it's waiting until your agent's first question", async () => {
  firstLaunch();
  renderHome();
  await userEvent.click(await screen.findByRole("button", { name: /Try the example app/ }));
  expect(await screen.findByRole("region", { name: "Your agent" })).toHaveTextContent("Waiting for your agent's first question");
  expect(screen.getByRole("button", { name: /I'll do it later/ })).toBeInTheDocument();
});

test("the welcome shows once: after it is done, the home page shows as usual", async () => {
  firstLaunch({ done: true });
  renderHome();
  expect(await screen.findByText("No projects yet")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "Welcome to FlowForge" })).not.toBeInTheDocument();
});

test("the keys step sets the Vault's lock when there is none", async () => {
  firstLaunch({ connected: true });
  renderHome();
  await userEvent.click(await screen.findByRole("button", { name: /Try the example app/ }));
  await userEvent.click(await screen.findByRole("button", { name: /^Next/ }));
  expect(await screen.findByRole("region", { name: "Set up the Vault" })).toBeInTheDocument();
  expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
});

test("if being done can't be saved, the welcome stays open and says so (Codex review)", async () => {
  firstLaunch();
  renderHome();
  const skip = await screen.findByRole("button", { name: /Skip for now/ });
  const original = globalThis.fetch;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) =>
    init?.method === "PATCH" ? new Response(JSON.stringify({ detail: "Disk full" }), { status: 500 }) : original(input, init));
  await userEvent.click(skip);
  expect(await screen.findByRole("alert")).toHaveTextContent("Disk full");
  expect(screen.getByRole("dialog", { name: "Welcome to FlowForge" })).toBeInTheDocument();
});
