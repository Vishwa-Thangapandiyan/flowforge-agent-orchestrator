import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { FLOW, TRACE } from "../test/flowFixture";

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
  await vi.waitFor(() => expect(calls.some((c) => c.url === "/flow?layer=planner")).toBe(true));
});

test("Test run starts the replay", async () => {
  api();
  renderAt("/");
  await screen.findByText("Fetch order", { selector: ".ff-title" });
  await userEvent.click(screen.getByRole("button", { name: /Test run/ }));
  const hud = await screen.findByRole("status");
  expect(within(hud).getByText(/Test order #17/)).toBeInTheDocument();
});

test("without a Planner the map explains when it arrives", async () => {
  mockApi({ "/meta": { ...META, example: false }, "/flow": { available: false, message: "The Planner maps your repo from Phase 5." }, "/connectors": [] });
  renderAt("/");
  expect(await screen.findByText("No map yet")).toBeInTheDocument();
  expect(screen.getByText("The Planner maps your repo from Phase 5.")).toBeInTheDocument();
});
