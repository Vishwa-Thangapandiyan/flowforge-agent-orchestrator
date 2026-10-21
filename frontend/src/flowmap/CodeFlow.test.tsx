import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { CODEFLOW, DEPS } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

const REAL = { ...META, example: false };
const routes = (flow: unknown) => ({
  "/meta": REAL, "/connectors": CONNECTORS, "/checks": { run_id: null, checked_at: null, summary: {}, items: [], example: false },
  "/flow?layer=mine": DEPS, "/flow?layer=mine&map=flow": flow,
});

test("the Flow switch shows the order the code calls its dependencies, and how it could be faster", async () => {
  mockApi(routes(CODEFLOW));
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" }, { timeout: 5000 });
  await userEvent.click(screen.getByRole("button", { name: "Flow" }));
  expect(await screen.findByText("fetch", { selector: ".ff-title" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Read from your code/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Test run/ })).not.toBeInTheDocument();   // nothing to replay (D25)
  const faster = screen.getByRole("region", { name: "Faster" });
  expect(within(faster).getByText("9.4 s")).toBeInTheDocument();   // as written
  expect(within(faster).getByText("9.2 s")).toBeInTheDocument();   // could be: the critical path
  expect(within(faster).getByText(/start them together with asyncio.gather/)).toBeInTheDocument();
  expect(within(faster).getByText("−0.2 s")).toBeInTheDocument();
  expect(within(faster).getByText(/could start even earlier/)).toBeInTheDocument();
});

test("pointing at a piece of advice lights up its blocks", async () => {
  mockApi(routes(CODEFLOW));
  renderAt("/?map=flow");
  await screen.findByText("fetch", { selector: ".ff-title" }, { timeout: 5000 });
  await userEvent.hover(screen.getByRole("button", { name: /Start these 2 together/ }));
  const lit = [...document.querySelectorAll(".ff-block.hit")].map((b) => b.querySelector(".ff-title")?.textContent);
  expect(lit.sort()).toEqual(["Open-Meteo", "fetch"]);
});

test("a repo without Python says why its flow waits", async () => {
  mockApi(routes({ available: false, message: "Flow order needs Python for now; Dart and JS/TS are next." }));
  renderAt("/?map=flow");
  expect(await screen.findByText("Flow order needs Python for now; Dart and JS/TS are next.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Folder to scan")).not.toBeInTheDocument();
});
