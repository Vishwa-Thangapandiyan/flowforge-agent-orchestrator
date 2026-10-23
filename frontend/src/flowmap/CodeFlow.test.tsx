import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { CODEFLOW, DEPS } from "../test/flowFixture";
import { only } from "./FlowMapPage";

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
  expect(await screen.findByRole("heading", { level: 1, name: "trip-planner" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Test run/ })).not.toBeInTheDocument();   // nothing to replay (D25)
  // a decision is a small ◆ mark: its question on hover and in the panel, not printed on the map (D33)
  const mark = document.querySelector(".ff-block.kind-decision.compact")!;
  expect(mark).toHaveAttribute("title", expect.stringContaining("?"));
  await userEvent.click(screen.getByRole("button", { name: "More" }));
  expect(screen.getByRole("menuitem", { name: /Re-scan the repo/ })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: /Export/ })).toHaveAttribute("href", "/map/export?map=flow");   // the MCP Map
  await userEvent.click(screen.getByRole("menuitemcheckbox", { name: /Show every check/ }));
  await vi.waitFor(() => expect(document.querySelector(".ff-block.kind-decision.compact")).toBeNull());
  const faster = screen.getByRole("region", { name: "Faster" });
  expect(within(faster).getByRole("button", { name: /Watch it run/ })).toBeInTheDocument();
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
  await userEvent.click(within(faster).getByRole("button", { name: /Copy prompt/ }));
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

test("a flow read from Dart says it was read by patterns and names Dart's import", async () => {
  const dart = {
    ...CODEFLOW, patterns: ["dart"],
    advice: (CODEFLOW.advice ?? []).map((a) => (a.change ? { ...a, change: { ...a.change, needs_import: false, import_text: "import 'dart:async';" } } : a)),
  };
  mockApi(routes(dart));
  renderAt("/?map=flow");
  const faster = await screen.findByRole("region", { name: "Faster" }, { timeout: 5000 });
  expect(within(faster).getByText("Dart read by patterns: less exact than Python.")).toBeInTheDocument();
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

test("with several actions, the flow shows one at a time, the slowest first (D33)", async () => {
  const start = CODEFLOW.nodes.find((n) => n.kind === "start")!;
  const api = CODEFLOW.nodes.find((n) => n.kind === "api")!;
  const twoActions = {
    ...CODEFLOW,
    nodes: [...CODEFLOW.nodes, { ...start, id: "start-other", title: "other()" }, { ...api, id: "api-extra-1", what: "Extra call" }],
    edges: [...CODEFLOW.edges, { ...CODEFLOW.edges[0], id: "start-other__api-extra-1", source: "start-other", target: "api-extra-1" }],
    actions: [
      { id: "start-plan", title: "plan()", written_ms: 9400, could_ms: 9220, path: CODEFLOW.critical_path.path, calls: 4 },
      { id: "start-other", title: "other()", written_ms: 300, could_ms: 300, path: ["start-other", "api-extra-1"], calls: 1 },
    ],
  };
  mockApi(routes(twoActions));
  renderAt("/?map=flow");
  const picker = await screen.findByRole("combobox", { name: /Action/ }, { timeout: 5000 });
  expect(Array.from((picker as HTMLSelectElement).options).map((o) => o.textContent)).toEqual(["plan() · 9.4 s", "other() · 300 ms"]);
  expect(await screen.findByText("About the city", { selector: ".ff-title" })).toBeInTheDocument();
  expect(screen.queryByText("Extra call", { selector: ".ff-title" })).not.toBeInTheDocument();
  await userEvent.selectOptions(picker, "start-other");
  expect(await screen.findByText("Extra call", { selector: ".ff-title" }, { timeout: 5000 })).toBeInTheDocument();
  expect(screen.queryByText("About the city", { selector: ".ff-title" })).not.toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Faster" })).getAllByText("300 ms").length).toBeGreaterThan(0);
}, 20000);

test("a step you added stays visible in the chosen action, so you can edit it", () => {
  const start = CODEFLOW.nodes.find((n) => n.kind === "start")!;
  const mine = { ...CODEFLOW.nodes.find((n) => n.kind === "api")!, id: "step_new", title: "New step", added_by: "user" as const };
  const flow = { ...CODEFLOW, nodes: [...CODEFLOW.nodes, { ...start, id: "start-other" }, mine] };
  const view = only(flow, { id: "start-plan", title: "plan()", written_ms: 9400, could_ms: 9220, path: [], calls: 4 });
  expect(view.nodes.map((n) => n.id)).toContain("step_new");
  expect(view.nodes.map((n) => n.id)).not.toContain("start-other");
});
