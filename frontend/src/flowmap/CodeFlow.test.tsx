import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { CODEFLOW, DEPS } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

const REAL = { ...META, example: false };
const routes = (flow: unknown) => ({
  "/meta": REAL, "/connectors": CONNECTORS, "/checks": { run_id: null, checked_at: null, summary: {}, items: [], example: false },
  "/flow?layer=mine": DEPS, "/flow?layer=mine&map=flow": flow, "/scan": { name: "trip-planner", example: false },
});

test("the Flow switch shows the order the code calls its dependencies, and how it could be faster", async () => {
  mockApi(routes(CODEFLOW));
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" }, { timeout: 5000 });
  await userEvent.click(screen.getByRole("button", { name: "Flow" }));
  // a block leads with what it does, in the code's own words; the service is underneath (D25)
  expect(await screen.findByText("About the city", { selector: ".ff-title" })).toBeInTheDocument();
  expect(screen.getByText("fetch · MCP server", { selector: ".ff-sub" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Read from your code/ })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { level: 1, name: "trip-planner" })).toBeInTheDocument();
  expect(screen.getByRole("banner")).toHaveTextContent("4 calls·1 decision");
  expect(screen.getByRole("button", { name: /Re-scan the repo/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Export/ })).toHaveAttribute("href", "/map/export?map=flow");   // the MCP Map (D26)
  expect(screen.queryByRole("button", { name: /Test run/ })).not.toBeInTheDocument();   // nothing to replay (D25)
  const faster = screen.getByRole("region", { name: "Faster" });
  expect(within(faster).getByText("9.4 s")).toBeInTheDocument();   // as written
  expect(within(faster).getByText("9.2 s")).toBeInTheDocument();   // could be: the critical path
  expect(within(faster).getByText(/start them together with asyncio.gather/)).toBeInTheDocument();
  expect(within(faster).getByText("−0.2 s")).toBeInTheDocument();
  expect(within(faster).getByText(/could start even earlier/)).toBeInTheDocument();
  expect(within(faster).getByText(/Can.t see: calls passed around as values/)).toBeInTheDocument();   // limits, said (D25)
});

test("each piece of advice shows the code change and copies a prompt for a coding agent (D27)", async () => {
  const copied: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { copied.push(t); } } });
  mockApi(routes(CODEFLOW));
  renderAt("/?map=flow");
  const faster = await screen.findByRole("region", { name: "Faster" }, { timeout: 5000 });
  await userEvent.click(within(faster).getByRole("button", { name: "Show the change" }));
  const change = within(faster).getByRole("region", { name: "The change" });
  expect(change).toHaveTextContent("planner.py · lines 60–61");
  expect(within(change).getByText("60")).toBeInTheDocument();   // the lines as they are, numbered
  expect(change).toHaveTextContent("forecast, background = await asyncio.gather(");
  await userEvent.click(within(change).getByRole("button", { name: /Copy the new code/ }));
  expect(copied[0].split("\n")[0]).toBe("    forecast, background = await asyncio.gather(");
  await userEvent.click(within(faster).getByRole("button", { name: /Copy prompt for your coding agent/ }));
  expect(copied[1]).toMatch(/^In planner.py, plan\(\) waits/);
  expect(await within(faster).findByText("Copied")).toBeInTheDocument();
});

test("pointing at a piece of advice lights up its blocks", async () => {
  mockApi(routes(CODEFLOW));
  renderAt("/?map=flow");
  await screen.findByText("About the city", { selector: ".ff-title" }, { timeout: 5000 });
  await userEvent.hover(screen.getByRole("button", { name: /Start these 2 together/ }));
  const lit = [...document.querySelectorAll(".ff-block.hit")].map((b) => b.querySelector(".ff-title")?.textContent);
  expect(lit.sort()).toEqual(["About the city", "Today's weather"]);
});

test("a repo without Python says why its flow waits", async () => {
  mockApi(routes({ available: false, message: "Flow order reads Python, Dart, JavaScript and TypeScript." }));
  renderAt("/?map=flow");
  expect(await screen.findByText("Flow order reads Python, Dart, JavaScript and TypeScript.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Folder to scan")).not.toBeInTheDocument();
});

test("Watch it run plays the could-be schedule, said plainly", async () => {
  mockApi(routes(CODEFLOW));
  renderAt("/?map=flow");
  await userEvent.click(await screen.findByRole("button", { name: /Watch it run/ }, { timeout: 5000 }));
  expect(await screen.findByRole("status")).toHaveTextContent("Watch it run · the could-be schedule, not a recording");
});

test("pointing at a block lights what it waits for and what waits for it", async () => {
  mockApi(routes(CODEFLOW));
  renderAt("/?map=flow");
  const weather = await screen.findByText("Today's weather", { selector: ".ff-title" }, { timeout: 5000 });
  await userEvent.hover(weather.closest(".react-flow__node")!);
  const lit = [...document.querySelectorAll(".ff-block.hit .ff-title")].map((t) => t.textContent).sort();
  // up: the city lookup and its check; down: the plan it feeds. fetch runs beside it, so it stays dim.
  expect(lit).toEqual(["Find the city", "Today's weather", "Write the plan", "plan()"]);
  expect(document.querySelector(".ff-block.miss .ff-title")).not.toBeNull();
  await userEvent.unhover(weather.closest(".react-flow__node")!);
  expect(document.querySelector(".ff-block.hit")).toBeNull();
  // the keyboard does the same: focus a block (D18: keyboard-reachable)
  act(() => (weather.closest(".react-flow__node") as HTMLElement).focus());
  expect([...document.querySelectorAll(".ff-block.hit .ff-title")].map((t) => t.textContent).sort())
    .toEqual(["Find the city", "Today's weather", "Write the plan", "plan()"]);
});

test("a flow read from Dart says it was read by patterns and names Dart's import (D32)", async () => {
  const dart = {
    ...CODEFLOW, patterns: ["dart"],
    advice: (CODEFLOW.advice ?? []).map((a) => (a.change ? { ...a, change: { ...a.change, needs_import: false, import_text: "import 'dart:async';" } } : a)),
  };
  mockApi(routes(dart));
  renderAt("/?map=flow");
  const faster = await screen.findByRole("region", { name: "Faster" }, { timeout: 5000 });
  expect(within(faster).getByText("Dart read by patterns: less exact than Python (D32).")).toBeInTheDocument();
  await userEvent.click(within(faster).getByRole("button", { name: "Show the change" }));
  expect(within(faster).getByText("import 'dart:async';")).toBeInTheDocument();
});

test("with several entry points, Faster shows the slowest action's calls, not every call added up (D32)", async () => {
  const second = {
    ...CODEFLOW,
    nodes: [...CODEFLOW.nodes,
      { ...CODEFLOW.nodes.find((n) => n.kind === "start")!, id: "start-other", title: "other()" },
      { ...CODEFLOW.nodes.find((n) => n.kind === "api")!, id: "api-extra-1", title: "Extra" }],
    edges: [...CODEFLOW.edges, { ...CODEFLOW.edges[0], id: "start-other__api-extra-1", source: "start-other", target: "api-extra-1" }],
  };
  mockApi(routes(second));
  renderAt("/?map=flow");
  const faster = await screen.findByRole("region", { name: "Faster" }, { timeout: 5000 });
  const entry = CODEFLOW.nodes.find((n) => n.id === CODEFLOW.critical_path.path[0])!;
  expect(faster).toHaveTextContent(`The slowest of 2 actions, ${entry.title}: its 4 calls`);
});
