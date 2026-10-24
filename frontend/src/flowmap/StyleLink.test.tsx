// A link to one map style (?style=boxed) beats the style Settings saved (D26, D40; Codex review). Its own file: the
// saved style is fetched once per page load, so this must be the first map this file opens.
import { screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { CODEFLOW, DEPS } from "../test/flowFixture";
import { SETTINGS } from "../test/settingsFixture";

beforeEach(() => localStorage.clear());
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

test("a link that names a style keeps it, even in a browser where Settings would choose another", async () => {
  const calls = mockApi({
    "/meta": { ...META, example: false }, "/connectors": CONNECTORS, "/scan": { name: "trip-planner", example: false },
    "/checks": { run_id: null, checked_at: null, summary: {}, items: [], example: false },
    "/flow?layer=mine": DEPS, "/flow?layer=mine&map=flow": CODEFLOW, "/settings": { ...SETTINGS, map_style: "metro" },
  });
  window.history.replaceState(null, "", "/?map=flow&style=boxed");   // the map reads the browser's own address
  renderAt("/?map=flow&style=boxed");
  await screen.findByRole("button", { name: /^Style/ });
  await vi.waitFor(() => expect(document.querySelector(".fm")).toHaveAttribute("data-graph", "boxed"));
  await new Promise((r) => setTimeout(r, 50));   // past the saved style's fetch, had it been made
  expect(document.querySelector(".fm")).toHaveAttribute("data-graph", "boxed");
  expect(calls.some((c) => c.url === "/settings")).toBe(false);
});
