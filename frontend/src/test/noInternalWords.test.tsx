import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { META, mockApi, renderAt } from "./api";
import { CONNECTORS } from "./fixtures";
import { CHECKS, CODEFLOW, DEPS, PLAN } from "./flowFixture";

// Decision numbers ("D25") and version words are ours, not the user's (D33): no page shows them.
const INTERNAL = /\(D\d+\)|\bD\d{1,2}\b|Flow v\d|Map v\d|fact sheet/;

const routes = {
  "/meta": META, "/connectors": CONNECTORS, "/checks": CHECKS, "/checks/plan": PLAN,
  "/flow?layer=mine": DEPS, "/flow?layer=mine&map=flow": CODEFLOW, "/scan": { name: "trip-planner", example: true },
  "/security": { repo: "trip-planner", scanned: true, summary: {}, findings: [] },
};

test.each([
  ["the map", "/", "Nominatim"],
  ["the flow", "/?map=flow", "About the city"],
  ["the checks", "/checks", "Checks"],
])("%s shows no internal words", async (_, path, ready) => {
  mockApi(routes);
  renderAt(path);
  await screen.findAllByText(ready, {}, { timeout: 6000 });
  expect(document.body.textContent).not.toMatch(INTERNAL);
}, 20000);
