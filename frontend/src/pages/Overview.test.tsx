import { screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { render } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { HubMap, layout } from "../components/HubMap";
import { healthTone, runTone, stepTone } from "../components/status";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS, HEALTH, SAVINGS, run } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

test("colour meanings are fixed", () => {
  expect(runTone("succeeded")[0]).toBe("teal");
  expect(runTone("running")[0]).toBe("blue");
  expect(runTone("failed")[0]).toBe("coral");
  expect(runTone("waiting")[0]).toBe("amber");
  expect(stepTone("running")[0]).toBe("blue");
  expect(stepTone("succeeded")).toEqual(["teal", "done"]);
  expect(healthTone("missing_key")).toBe("amber");
  expect(healthTone("failing")).toBe("coral");
});

test("hub map: one box per app, each a link with its status, links of running apps animate", () => {
  const health = Object.fromEntries(HEALTH.map((h) => [h.id, h]));
  const { container } = render(
    <MemoryRouter>
      <HubMap project="Baby-care shop" connectors={CONNECTORS} health={health} active={new Set(["razorpay"])} />
    </MemoryRouter>,
  );
  const links = screen.getAllByRole("link");
  expect(links).toHaveLength(CONNECTORS.length);
  expect(screen.getByRole("link", { name: /^Razorpay.*OK, 2 min ago$/ })).toHaveAttribute("href", "/connectors/razorpay");
  expect(screen.getByRole("link", { name: /^Gemini.*Key missing$/ })).toBeInTheDocument();
  expect(container.querySelectorAll(".hub-line.live")).toHaveLength(1);
  expect(container.querySelector(".hub-core")).toHaveTextContent("Baby-care shop");
  expect(container.querySelector('[data-brand="Razorpay"]')).not.toBeNull(); // brand mark, not a monogram
  expect(container.querySelector('[data-brand="Google Gemini"]')).not.toBeNull();
});

test("layout spreads apps around the hub without stacking", () => {
  const spots = layout(6);
  expect(new Set(spots.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)).size).toBe(6);
  expect(spots[0]).toEqual({ x: 50, y: 11 }); // the first app sits at the top
});

test("overview shows apps, health, savings and what needs you", async () => {
  mockApi({
    "/meta": META, "/connectors": CONNECTORS, "/health/tools": HEALTH, "/stats/savings": SAVINGS,
    "/runs": [run({ id: "r1", status: "running", connectors: ["razorpay"] }), run({ id: "r0", status: "succeeded" })],
  });
  renderAt("/");
  expect(await screen.findByRole("heading", { name: "Baby-care shop", level: 1 })).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /Nightly finance check is running/ })).toHaveAttribute("href", "/runs/r1");
  const health = await screen.findByRole("region", { name: "Tool health" });
  expect(within(health).getByText("31 of 40 calls left this minute")).toBeInTheDocument();
  const needs = screen.getByRole("region", { name: "Needs you" });
  expect(within(needs).getByText("Gemini has no key yet")).toBeInTheDocument();
  expect(within(needs).getByText("Sirius is failing")).toBeInTheDocument();
  expect(within(needs).getByText(/scan crashed/)).toBeInTheDocument();
  const money = screen.getByRole("region", { name: "Money and time" });
  expect(within(money).getByText("calls skipped by cache")).toBeInTheDocument();
});
