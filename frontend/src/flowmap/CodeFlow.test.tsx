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

test("pointing at a piece of advice lights up its blocks", async () => {
  mockApi(routes(CODEFLOW));
  renderAt("/?map=flow");
  await screen.findByText("About the city", { selector: ".ff-title" }, { timeout: 5000 });
  await userEvent.hover(screen.getByRole("button", { name: /Start these 2 together/ }));
  const lit = [...document.querySelectorAll(".ff-block.hit")].map((b) => b.querySelector(".ff-title")?.textContent);
  expect(lit.sort()).toEqual(["About the city", "Today's weather"]);
});

test("a repo without Python says why its flow waits", async () => {
  mockApi(routes({ available: false, message: "Flow order needs Python for now; Dart and JS/TS are next." }));
  renderAt("/?map=flow");
  expect(await screen.findByText("Flow order needs Python for now; Dart and JS/TS are next.")).toBeInTheDocument();
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
