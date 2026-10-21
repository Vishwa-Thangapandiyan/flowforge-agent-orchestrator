import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { CODEFLOW, DEPS } from "../test/flowFixture";

const NO_CHECKS = { run_id: null, checked_at: null, summary: {}, items: [], example: false };
const routes = {
  "/meta": { ...META, example: false }, "/connectors": CONNECTORS, "/checks": NO_CHECKS,
  "/flow?layer=mine": DEPS, "/flow?layer=mine&map=flow": CODEFLOW, "/scan": { name: "trip-planner", example: false },
};

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

async function pick(theme: string) {
  await userEvent.click(await screen.findByRole("button", { name: /^Style:/ }, { timeout: 5000 }));
  await userEvent.click(screen.getByRole("menuitemradio", { name: new RegExp(theme) }));
}

test("the theme menu switches how the map looks, and remembers it for this viewer", async () => {
  mockApi(routes);
  renderAt("/?map=flow");
  await pick("Blueprint");
  expect(document.querySelector(".fm")).toHaveAttribute("data-graph", "blueprint");
  expect(screen.getByRole("button", { name: "Style: Blueprint" })).toBeInTheDocument();
  expect(localStorage.getItem("flowforge.graphTheme")).toBe("blueprint");
});

test("Boxed puts what starts together in one box", async () => {
  mockApi(routes);
  renderAt("/?map=flow");
  await pick("Boxed");
  // Open-Meteo and fetch both start once the city check passes (see CODEFLOW)
  const box = await screen.findByRole("group", { name: /Start together/ });
  expect(within(box).getByText(/0\.4 s/)).toBeInTheDocument();
});

test("Boxed groups a dependency map by kind", async () => {
  mockApi(routes);
  renderAt("/");
  await pick("Boxed");
  expect(await screen.findByRole("group", { name: "APIs" })).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "MCP servers" })).toBeInTheDocument();
});

test("Metro draws stations, and lines take the colour of the kind they lead to", async () => {
  mockApi(routes);
  renderAt("/?map=flow");
  await pick("Metro");
  expect(document.querySelectorAll(".ff-station").length).toBeGreaterThan(3);
  expect(document.querySelector(".ff-edge.to-mcp")).not.toBeNull();
});
