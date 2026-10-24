import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { routes } from "../routes";
import { META, mockApi, renderAt, renderHome } from "../test/api";
import { DEPS } from "../test/flowFixture";

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

const card = (id: string, name: string, extra = {}) => ({
  id, name, path: `/home/me/code/${id}`, added: "2026-10-20T10:00:00Z", opened: new Date(Date.now() - 2 * 3600e3).toISOString(),
  missing: false, summary: { dependencies: 12, issues: 3, keys_missing: 1 }, ...extra,
});
const PROJECTS = {
  default: "shop", example: { id: "example", name: "Example: trip planner" },
  projects: [card("shop", "shop"), card("blog", "My blog", { summary: { dependencies: 4, issues: 0, keys_missing: 0 } })],
};

function api(projects: object = PROJECTS) {
  return mockApi({
    "/projects": () => projects, "/meta": META, "/flow": DEPS, "/connectors": [], "/security": { findings: [] },
    "/issues": { repo: "shop", example: false, summary: {}, issues: [] }, "/keys": { repo: "shop", example: false, summary: {}, keys: [] },
    "/projects/shop/open": { id: "shop", opened: true }, "/projects/blog/open": { id: "blog", opened: true },
    "/projects/blog": (init?: RequestInit) => (init?.method === "DELETE" ? { id: "blog", removed: true } : { ...card("blog", "Blog 2") }),
  });
}

test("the home page shows every project with what needs you, the example, and New project", async () => {
  api();
  renderHome();
  const shop = await screen.findByRole("button", { name: "Open shop" });
  expect(shop).toHaveTextContent(/12 dependencies.*⚠ 3 to fix.*🔑 1 missing.*opened 2 h ago/);
  expect(screen.getByRole("button", { name: "Open My blog" })).toHaveTextContent("✓ nothing to fix");
  expect(screen.getByText("Example: trip planner")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: /New project/ })[0]).toHaveAttribute("href", "/projects/new");
});

test("opening a project goes to its map and says it was opened", async () => {
  const calls = api();
  renderHome();
  await userEvent.click(await screen.findByRole("button", { name: "Open shop" }));
  expect(calls.some((c) => c.url === "/projects/shop/open" && c.init?.method === "POST")).toBe(true);
  expect(await screen.findByText("Nominatim", { selector: ".ff-title" })).toBeInTheDocument();
  expect(calls.some((c) => c.url.split("?")[0] === "/flow")).toBe(true);   // the project's own map
});

test("a project can be renamed or removed; removing asks first", async () => {
  const calls = api();
  vi.stubGlobal("confirm", vi.fn(() => true));
  renderHome();
  await userEvent.click(await screen.findByRole("button", { name: "More for My blog" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
  const box = screen.getByLabelText("New name for My blog");
  await userEvent.clear(box);
  await userEvent.type(box, "Blog 2");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(JSON.parse(String(calls.find((c) => c.init?.method === "PATCH")?.init?.body))).toEqual({ name: "Blog 2" });
  await userEvent.click(screen.getByRole("button", { name: "More for My blog" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Remove from FlowForge" }));
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("your folder and code stay"));
  expect(calls.some((c) => c.url === "/projects/blog" && c.init?.method === "DELETE")).toBe(true);
});

test("a new project is its folder, scanned, then its map", async () => {
  const calls = mockApi({
    "/projects": (init?: RequestInit) => (init?.method === "POST" ? card("blog", "blog") : PROJECTS),
    "/meta": META, "/flow": DEPS, "/connectors": [], "/security": { findings: [] },
    "/issues": { repo: "blog", example: false, summary: {}, issues: [] }, "/keys": { repo: "blog", example: false, summary: {}, keys: [] },
  });
  const router = createMemoryRouter(routes, { initialEntries: ["/projects/new"] });
  render(<RouterProvider router={router} />);
  await userEvent.type(await screen.findByLabelText("Your app's folder"), "/home/me/code/blog");
  await userEvent.click(screen.getByRole("button", { name: /Scan/ }));
  expect(JSON.parse(String(calls.find((c) => c.url === "/projects" && c.init?.method === "POST")?.init?.body)))
    .toEqual({ path: "/home/me/code/blog" });
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  expect(router.state.location.pathname).toBe("/p/blog");
});

test("the picker lists your open projects; switching brings you back where you were; × closes without deleting", async () => {
  const calls = api();
  const router = createMemoryRouter(routes, { initialEntries: ["/p/blog/keys"] });
  render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { level: 1, name: "Keys" });
  await router.navigate("/p/shop/issues");   // open a second project, on its Issues page
  await screen.findByRole("heading", { level: 1, name: "Issues" });
  await userEvent.click(screen.getByRole("button", { name: /Project: shop/ }));
  const menu = screen.getByRole("menu", { name: "Projects" });
  expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual([
    expect.stringContaining("shop"), expect.stringContaining("My blog"), "⌂ All projects", "+ New project"]);
  await userEvent.click(within(menu).getByRole("menuitem", { name: /My blog/ }));
  await screen.findByRole("heading", { level: 1, name: "Keys" });                // where you left it
  expect(router.state.location.pathname).toBe("/p/blog/keys");
  await userEvent.click(screen.getByRole("button", { name: /Project: My blog/ }));
  await userEvent.click(screen.getByRole("button", { name: "Close shop" }));
  expect(within(screen.getByRole("menu", { name: "Projects" })).queryByRole("menuitem", { name: /^SH/ })).not.toBeInTheDocument();
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);            // the project itself stays
});

test("an address from before projects opens the default project's page", async () => {
  api();
  const router = createMemoryRouter(routes, { initialEntries: ["/issues"] });
  render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { level: 1, name: "Issues" });
  expect(router.state.location.pathname).toBe("/p/shop/issues");
});

test("inside a project, the rail's links stay in it", async () => {
  api();
  renderAt("/keys");
  await screen.findByRole("heading", { level: 1, name: "Keys" });
  const nav = screen.getByRole("navigation", { name: "Main" });
  expect(within(nav).getByRole("link", { name: /Issues/ })).toHaveAttribute("href", "/p/test/issues");
  expect(within(nav).getByRole("link", { name: /^Map/ })).toHaveAttribute("href", "/p/test");
});

test("old addresses inside a project stay in it: /security opens its Issues, /plans its map (Codex review)", async () => {
  api();
  const router = createMemoryRouter(routes, { initialEntries: ["/p/blog/security"] });
  render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { level: 1, name: "Issues" });
  expect(router.state.location.pathname).toBe("/p/blog/issues");
  await router.navigate("/p/blog/plans");
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/p/blog"));
});
