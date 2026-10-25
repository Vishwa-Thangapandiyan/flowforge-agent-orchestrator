import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";

afterEach(() => vi.unstubAllGlobals());

const FAKE = "sk_test_FAKEFAKE12345678";
const ARGV = ["flutter", "run", "--dart-define=STRIPE_SECRET_KEY=ffkey://STRIPE_SECRET_KEY"];
const KEYS = { repo: "shop", example: false, summary: {}, keys: [], run: "flowforge run --repo /home/me/shop --" };

function api(apps: object, extra = {}) {
  return mockApi({ "/meta": META, "/issues": { repo: "shop", example: false, summary: {}, issues: [] }, "/keys": KEYS,
    "/apps": () => apps, ...extra });
}

test("every page shows what your agent wants to run, with the key names, and Allow sends your yes (D43)", async () => {
  const calls = api({ requests: [{ id: "r1", argv: ARGV, keys: ["STRIPE_SECRET_KEY"], at: 0, state: "waiting" }], runs: [],
    approve_runs: true }, { "/apps/requests/r1/allow": { state: "allowed" } });
  renderAt("/checks");
  const card = await screen.findByRole("alertdialog", { name: "Your agent wants to run" });
  expect(card).toHaveTextContent("flutter run --dart-define=STRIPE_SECRET_KEY=ffkey://STRIPE_SECRET_KEY");
  expect(card).toHaveTextContent("with STRIPE_SECRET_KEY");
  await userEvent.click(within(card).getByRole("button", { name: /Allow/ }));
  expect(calls.some((c) => c.url === "/apps/requests/r1/allow" && c.init?.method === "POST")).toBe(true);
  expect(document.body.innerHTML).not.toContain(FAKE);
});

test("Deny sends a no", async () => {
  const calls = api({ requests: [{ id: "r2", argv: ["npm", "run", "dev"], keys: [], at: 0, state: "waiting" }], runs: [],
    approve_runs: true }, { "/apps/requests/r2/deny": { state: "denied" } });
  renderAt("/checks");
  await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Deny" }));
  expect(calls.some((c) => c.url === "/apps/requests/r2/deny")).toBe(true);
});

test("no request, no card", async () => {
  api({ requests: [], runs: [], approve_runs: true });
  renderAt("/checks");
  await screen.findByRole("navigation", { name: "Main" });
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

test("the Keys page lists your agent's runs with Stop and masked output", async () => {
  const run = { id: "x1", argv: ARGV, keys: ["STRIPE_SECRET_KEY"], status: "running", code: null, started: Date.now() / 1000 };
  const calls = api({ requests: [], runs: [run], approve_runs: true }, {
    "/apps/runs/x1/output": { lines: [[1, "key [REDACTED]"]] }, "/apps/runs/x1/stop": { id: "x1", stopped: true } });
  renderAt("/keys");
  const list = await screen.findByRole("region", { name: "Agent runs" });
  expect(list).toHaveTextContent("running");
  expect(list).toHaveTextContent("keys: STRIPE_SECRET_KEY");
  await userEvent.click(within(list).getByText("Output"));
  expect(await within(list).findByLabelText("Output (masked)")).toHaveTextContent("key [REDACTED]");
  await userEvent.click(within(list).getByRole("button", { name: /Stop/ }));
  expect(calls.some((c) => c.url === "/apps/runs/x1/stop" && c.init?.method === "POST")).toBe(true);
});
