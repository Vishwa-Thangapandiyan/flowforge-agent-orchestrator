import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import type { FlowNode } from "../api/types";
import { CODEFLOW, DEPS } from "../test/flowFixture";
import { autoLayout, sizeOf } from "./layout";
import { adoptMapStyle, timeColumns } from "./themes";

const NO_CHECKS = { run_id: null, checked_at: null, summary: {}, items: [], example: false };
const routes = {
  "/meta": { ...META, example: false }, "/connectors": CONNECTORS, "/checks": NO_CHECKS,
  "/flow?layer=mine": DEPS, "/flow?layer=mine&map=flow": CODEFLOW, "/scan": { name: "trip-planner", example: false },
};

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

async function pick(theme: string) {
  await userEvent.click(await screen.findByRole("button", { name: /^Style/ }));
  await userEvent.click(screen.getByRole("menuitemradio", { name: new RegExp(theme) }));
}

test("the theme menu switches how the map looks, and remembers it for this viewer", async () => {
  mockApi(routes);
  renderAt("/?map=flow");
  await pick("Blueprint");
  expect(document.querySelector(".fm")).toHaveAttribute("data-graph", "blueprint");
  expect(screen.getByRole("menuitemradio", { name: /Blueprint/ })).toHaveAttribute("aria-checked", "true");
  expect(localStorage.getItem("flowforge.graphTheme")).toBe("blueprint");
});

test("a map already open takes the style Settings saved when it arrives (D40, Codex review)", async () => {
  mockApi(routes);
  renderAt("/?map=flow");
  await screen.findByRole("button", { name: /^Style/ });
  expect(document.querySelector(".fm")).toHaveAttribute("data-graph", "studio");
  act(() => adoptMapStyle("metro"));
  await vi.waitFor(() => expect(document.querySelector(".fm")).toHaveAttribute("data-graph", "metro"));   // after the redraw
  expect(localStorage.getItem("flowforge.graphTheme")).toBe("metro");
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

test("Boxed's time columns leave room: no block touches another, and a block reached through a server sits level with it", () => {
  const via: FlowNode = { ...CODEFLOW.nodes.find((n) => n.id === "api-nominatim-1")!, id: "api-wikipedia-1", title: "Wikipedia",
    what: "through fetch", estimate_ms: 0 };
  const flow = { ...CODEFLOW, nodes: [...CODEFLOW.nodes, via],
    edges: [...CODEFLOW.edges, { id: "v", source: "mcp-fetch-1", target: "api-wikipedia-1", kind: "flow" as const, when: null, max: null, on: null, label: null }] };
  const at = timeColumns(flow, autoLayout(flow.nodes, flow.edges));
  const rect = (id: string) => {
    const s = sizeOf(flow.nodes.find((n) => n.id === id)!.kind);
    return { x: at[id][0], y: at[id][1] - 24, r: at[id][0] + s.w, b: at[id][1] + s.h + 24 };   // with the label room
  };
  const ids = Object.keys(at);
  for (const a of ids) for (const b of ids) {
    if (a >= b) continue;
    const p = rect(a), q = rect(b);
    expect(p.r <= q.x || q.r <= p.x || p.b <= q.y || q.b <= p.y, `${a} touches ${b}`).toBe(true);
  }
  expect(at["api-wikipedia-1"][1]).toBe(at["mcp-fetch-1"][1]);
  expect(at["api-wikipedia-1"][0]).toBeGreaterThan(at["mcp-fetch-1"][0]);
});
