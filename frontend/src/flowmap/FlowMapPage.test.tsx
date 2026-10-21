import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { DEPS, FLOW, TRACE } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

function api(extra: Record<string, unknown> = {}) {
  return mockApi({ "/meta": META, "/flow": FLOW, "/flow/trace": TRACE, "/connectors": CONNECTORS, ...extra });
}

test("the home page is the Planner's map of the app", async () => {
  api();
  renderAt("/");
  expect(await screen.findByRole("heading", { name: "Baby-care shop", level: 1 })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /The Planner drew this map/ })).toHaveAttribute("href", "/map/how");
  expect(await screen.findAllByText("Score fraud risk", { selector: ".ff-title" })).toHaveLength(2); // Gemini and its fallback
  expect(screen.getByText("Risky order?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /1 step unconfirmed/ })).toBeInTheDocument();
  expect(screen.getByRole("toolbar", { name: "Map tools" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Planner's map" })).toHaveAttribute("aria-pressed", "false");
  // the engine behind the Planner is never named
  expect(screen.getByRole("banner").textContent).not.toMatch(/NIM|llama|NVIDIA/);
});

test("search highlights matching steps", async () => {
  api();
  renderAt("/");
  await screen.findByText("Fetch order", { selector: ".ff-title" });
  await userEvent.type(screen.getByLabelText("Find a step"), "gemini");
  expect(screen.getByText("1 found")).toBeInTheDocument();
  expect(document.querySelector(".ff-block.hit")).toHaveTextContent("Score fraud risk");
});

test("the layer switch asks for the Planner's own version", async () => {
  const calls = api();
  renderAt("/");
  await screen.findByText("Fetch order", { selector: ".ff-title" });
  await userEvent.click(screen.getByRole("button", { name: "Planner's map" }));
  await vi.waitFor(() => expect(calls.some((c) => c.url.startsWith("/flow?layer=planner"))).toBe(true));
});

test("Test run starts the replay", async () => {
  api();
  renderAt("/");
  await screen.findByText("Fetch order", { selector: ".ff-title" });
  await userEvent.click(screen.getByRole("button", { name: /Test run/ }));
  const hud = await screen.findByRole("status");
  expect(within(hud).getByText(/Test order #17/)).toBeInTheDocument();
});

test("a dependency map shows what the app uses, without a test run or critical path", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": CONNECTORS });
  renderAt("/");
  expect(await screen.findByText("Nominatim", { selector: ".ff-title" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("trip-planner");   // the scanned folder
  const banner = screen.getByRole("banner");
  expect(within(banner).getByText("6 dependencies")).toBeInTheDocument();
  expect(within(banner).queryByText(/gates/)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Scanned from your code/ })).toHaveAttribute("href", "/map/how");
  expect(screen.queryByRole("button", { name: /Test run/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Critical path/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Add dependency/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Re-scan the repo/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "As scanned" })).toBeInTheDocument();   // no Planner drew it
  expect(screen.getByText("Your coding tools", { selector: ".ff-title" })).toBeInTheDocument();
});

test("example mode has one map, and Scan a folder says how to map your own", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": CONNECTORS });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  // nothing drawn by hand reaches the dashboard (D23)
  expect(screen.queryByRole("group", { name: "Which map" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Scan a folder/ }));
  expect(screen.getByText(/flowforge --repo/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Folder to scan")).not.toBeInTheDocument();
});

test("with a map, a different folder replaces it only after you confirm", async () => {
  const bodies: unknown[] = [];
  mockApi({
    "/meta": { ...META, example: false }, "/flow": DEPS, "/connectors": CONNECTORS,
    "/scan": (init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      bodies.push(body);
      return body.replace ? { repo: "/home/me/shop", name: "shop", version: 1 }
        : new Response(JSON.stringify({ detail: "This database maps trip-planner." }), { status: 409 });
    },
  });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  await userEvent.click(screen.getByRole("button", { name: /Scan a folder/ }));
  await userEvent.type(screen.getByLabelText("Folder to scan"), "/home/me/shop");
  await userEvent.click(screen.getByRole("button", { name: "Scan this folder" }));
  const replace = await screen.findByRole("button", { name: /Replace the map/ });
  expect(screen.getByText(/trip-planner's map and its versions are deleted/)).toBeInTheDocument();
  await userEvent.click(replace);
  await vi.waitFor(() => expect(bodies).toEqual([{ path: "/home/me/shop" }, { path: "/home/me/shop", replace: true }]));
});

test("without a map, you scan a folder", async () => {
  let scanned: unknown = null;
  mockApi({
    "/meta": { ...META, example: false }, "/connectors": [],
    "/flow": { available: false, message: "No map yet. Scan a folder to draw what your app depends on." },
    "/scan": (init?: RequestInit) => { scanned = JSON.parse(String(init?.body)); return { repo: "/home/me/shop", name: "shop", version: 1 }; },
  });
  renderAt("/");
  expect(await screen.findByText("No map yet")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Folder to scan"), "/home/me/shop");
  await userEvent.click(screen.getByRole("button", { name: "Scan this folder" }));
  await vi.waitFor(() => expect(scanned).toEqual({ path: "/home/me/shop" }));
});
