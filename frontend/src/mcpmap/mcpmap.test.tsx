import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CODEFLOW, DEPS } from "../test/flowFixture";
import { layoutMap, LANES } from "./layout";
import { toMermaid } from "./mermaid";

afterEach(() => vi.unstubAllGlobals());

test("the MCP Map puts each kind in its lane and each call where its inputs are ready (rules 1 and 2)", () => {
  const map = layoutMap(CODEFLOW);
  expect(LANES.map((l) => l.label)).toEqual(["Decisions", "LLMs", "MCP servers", "APIs", "Local programs"]);
  const at = Object.fromEntries(map.blocks.map((b) => [b.id, b]));
  expect(at["mcp-fetch-1"].lane).toBe("mcp");
  expect(at["if-1"].lane).toBe("decision");
  expect(at["mcp-fetch-1"].start).toBe(420);
  expect(at["mcp-fetch-1"].end - at["mcp-fetch-1"].start).toBe(6800);   // a bar as long as the call
  expect(at["llm-ollama-1"].start).toBe(7220);                         // after its slowest input
  expect(map.timed).toBe(true);
  expect(layoutMap(DEPS).timed).toBe(false);                            // dependencies only: no time axis
});

test("Mermaid keeps the shapes, the branches and the critical path, for a README", () => {
  const text = toMermaid(CODEFLOW, "trip-planner");
  expect(text.split("\n")[0]).toBe("flowchart LR");
  expect(text).toContain('start-plan(("plan()"))');
  expect(text).toContain('mcp-fetch-1{{"About the city<br/>fetch · 6.8 s"}}');
  expect(text).toContain('api-nominatim-1["Find the city<br/>Nominatim · 420 ms"]');
  expect(text).toContain('llm-ollama-1(["Write the plan<br/>Ollama · 2.0 s est."])');
  expect(text).toContain("if-1 -->|no| api-open-meteo-1");
  expect(text).toContain("if-1 ==>|no| mcp-fetch-1");
  expect(text).toContain("api-nominatim-1 ==> if-1");   // on the critical path
});

test("the export page draws the MCP Map and sends it out in every format", async () => {
  const writes: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { writes.push(t); } } });
  mockApi({ "/meta": { ...META, example: false }, "/flow?layer=mine&map=flow": CODEFLOW, "/scan": { name: "trip-planner", example: false } });
  renderAt("/map/export?map=flow");
  expect(await screen.findByRole("heading", { name: "MCP Map", level: 1 }, { timeout: 5000 })).toBeInTheDocument();
  const svg = screen.getByRole("img", { name: /MCP map of trip-planner/ });
  expect(svg).toHaveTextContent("trip-planner");
  expect(svg).toHaveTextContent("MCP servers");
  for (const name of ["Download SVG", "PNG", "PDF", "Copy as Mermaid", "Flow JSON"]) {
    expect(screen.getByRole("button", { name: new RegExp(name) })).toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("button", { name: /Copy as Mermaid/ }));
  expect(writes[0]).toMatch(/^flowchart LR/);
  expect(await screen.findByText("Copied")).toBeInTheDocument();
});
