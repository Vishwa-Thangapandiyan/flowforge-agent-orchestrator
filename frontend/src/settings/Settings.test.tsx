import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { SETTINGS } from "../test/settingsFixture";

beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute("data-theme"); });
afterEach(() => vi.unstubAllGlobals());

const FAKE = "sk_test_FAKEFAKE12345678";
function api(extra = {}) {
  return mockApi({ "/meta": META, "/settings": SETTINGS, ...extra });
}

test("Settings has four cards for every project, and nothing secret", async () => {
  api();
  renderAt("/settings");
  expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  expect(await screen.findByRole("region", { name: /Your agent · paired once/ })).toHaveTextContent("Connected");
  const vault = screen.getByRole("region", { name: /Keys & Vault/ });
  expect(vault).toHaveTextContent("Set");
  expect(vault).toHaveTextContent("your keychain");
  expect(within(vault).getByRole("link", { name: /Open the Vault/ })).toHaveAttribute("href", "/p/test/vault");
  const data = screen.getByRole("region", { name: /Data & checks/ });
  expect(data).toHaveTextContent("/home/me/.flowforge · 2 projects · 3.3 MB");
  expect(data).toHaveTextContent("shop1.1 MB · 12 checks · 1 server allowed");
  expect(data).toHaveTextContent("FlowForge 0.3.0 · installed with uvx");
  expect(document.body.innerHTML).not.toContain(FAKE);
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
});

test("the theme and the map style are picked in Settings", async () => {
  const calls = api();
  renderAt("/settings");
  await userEvent.click(await screen.findByRole("button", { name: /Dark/ }));
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(localStorage.getItem("flowforge.theme")).toBe("dark");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: /Maps open in/ }), "metro");
  expect(localStorage.getItem("flowforge.graphTheme")).toBe("metro");
  const patch = calls.find((c) => c.url === "/settings" && c.init?.method === "PATCH");
  expect(JSON.parse(String(patch?.init?.body))).toEqual({ map_style: "metro" });
});

test("clearing a project's check history asks first, then touches only that project", async () => {
  const calls = api({ "/projects/shop/checks": { id: "shop", checks: 0 } });
  renderAt("/settings");
  const shop = (await screen.findByText("shop", { selector: "b" })).closest("li")!;
  expect(within(screen.getByText("My blog", { selector: "b" }).closest("li")!).getByRole("button", { name: "Clear check history" })).toBeDisabled();
  await userEvent.click(within(shop).getByRole("button", { name: "Clear check history" }));
  expect(within(shop).getByRole("group", { name: "Are you sure?" })).toHaveTextContent("Clear 12 checks?");
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  await userEvent.click(within(shop).getByRole("button", { name: "Yes" }));
  expect(calls.filter((c) => c.init?.method === "DELETE").map((c) => c.url)).toEqual(["/projects/shop/checks"]);
});

test("the update check asks only when pressed", async () => {
  const calls = api({ "/settings/update-check": { current: "0.3.0", latest: "0.4.0", newer: true } });
  renderAt("/settings");
  const button = await screen.findByRole("button", { name: /Check for updates/ });
  expect(calls.some((c) => c.url.endsWith("/update-check"))).toBe(false);
  await userEvent.click(button);
  expect(await screen.findByText("0.4.0 is out")).toBeInTheDocument();
});

test("Settings opens from the home page too, outside any project", async () => {
  const { render } = await import("@testing-library/react");
  const { createMemoryRouter, RouterProvider } = await import("react-router-dom");
  const { routes } = await import("../routes");
  api();
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/settings"] })} />);
  expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
});

test("the Look card follows a map style that arrives after it opened (Codex review)", async () => {
  const { act } = await import("@testing-library/react");
  const { adoptMapStyle } = await import("../flowmap/themes");
  api();
  renderAt("/settings");
  expect(await screen.findByRole("combobox", { name: /Maps open in/ })).toHaveValue("studio");
  act(() => adoptMapStyle("blueprint"));
  // found again: the page re-reads every few seconds and may have drawn the card anew
  await vi.waitFor(() => expect(screen.getByRole("combobox", { name: /Maps open in/ })).toHaveValue("blueprint"));
});

test("a map style that can't be saved says so (Codex review)", async () => {
  api({ "/settings": (init?: RequestInit) => (init?.method === "PATCH"
    ? new Response(JSON.stringify({ detail: "Disk full" }), { status: 500 }) : SETTINGS) });
  renderAt("/settings");
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: /Maps open in/ }), "metro");
  expect(await screen.findByRole("alert")).toHaveTextContent("Kept in this browser only: Disk full");
});

test("Settings turns to Connected when your agent's first question arrives while it's open (Codex review)", async () => {
  let reads = 0;
  api({ "/settings": () => {
    reads += 1;
    return reads === 1 ? { ...SETTINGS, agent: { ...SETTINGS.agent, connected: false, last_call: null } } : SETTINGS;
  } });
  renderAt("/settings");
  const agent = await screen.findByRole("region", { name: /Your agent · paired once/ });
  expect(agent).toHaveTextContent("Waiting for your agent's first question");
  await vi.waitFor(() => expect(agent).toHaveTextContent("Connected"), { timeout: 8000 });
});

test("the desktop app's Settings adds the flowforge command to the terminal (D50)", async () => {
  let added = false;
  const calls = api({
    "/settings/terminal": (init?: RequestInit) => {
      if (init?.method === "POST") { added = true; return { message: "Done. Open a new terminal and type: flowforge status" }; }
      return { available: true, works: added, ours: added, finds: added ? "/x/flowforge" : null, system: "macos" };
    },
  });
  renderAt("/settings");
  const card = await screen.findByRole("region", { name: /Terminal/ });
  await userEvent.click(within(card).getByRole("button", { name: /Add the flowforge command/ }));
  expect(calls.some((c) => c.url === "/settings/terminal" && c.init?.method === "POST")).toBe(true);
  expect(await within(card).findByText(/Open a new terminal/)).toBeInTheDocument();
  expect(await within(card).findByText(/works in your terminal/)).toBeInTheDocument();
});

test("outside the desktop app there is no Terminal card", async () => {
  api({ "/settings/terminal": { available: false, works: true, ours: false, finds: null, system: "linux" } });
  renderAt("/settings");
  await screen.findByRole("region", { name: /Your agent · paired once/ });
  expect(screen.queryByRole("region", { name: /Terminal/ })).not.toBeInTheDocument();
});
