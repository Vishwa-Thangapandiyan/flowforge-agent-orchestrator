import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS, run } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

const RUNS = [
  run({ id: "a41c9e000000", status: "running", time_ms: null, plan: "Nightly finance check" }),
  run({ id: "7be310000000", status: "succeeded", plan: "Security scan", time_ms: 6400, cache_hits: 0, tokens: 0 }),
  run({ id: "30c7f5000000", status: "failed", plan: "Swap Razorpay to Stripe", time_ms: 5600, cache_hits: 3,
    failure_reason: 'Step "Fetch Stripe lifecycle" failed: could not start its MCP server. 3 steps after it were skipped.' }),
];

test("history lists runs with status chips, times, cache and tokens, and explains the failure", async () => {
  mockApi({ "/meta": META, "/runs": RUNS, "/connectors": CONNECTORS });
  renderAt("/runs");
  const table = await screen.findByRole("table");
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(4);
  expect(within(rows[1]).getByText("running")).toBeInTheDocument();
  expect(within(rows[1]).getByRole("link", { name: "a41c9e" })).toHaveAttribute("href", "/runs/a41c9e000000");
  expect(within(rows[2]).getByText("6.4 s")).toBeInTheDocument();
  expect(within(rows[3]).getByText("failed")).toBeInTheDocument();
  const why = screen.getByRole("region", { name: "Why it failed" });
  expect(why).toHaveTextContent("could not start its MCP server");
  expect(why).toHaveTextContent("3 steps after it were skipped");
});

test("filters ask the API for that status; waiting-for-you is not available yet", async () => {
  const calls = mockApi({ "/meta": META, "/runs": RUNS, "/connectors": CONNECTORS });
  renderAt("/runs");
  await screen.findByRole("table");
  fireEvent.click(screen.getByRole("button", { name: "Failed" }));
  await vi.waitFor(() => expect(calls.some((c) => c.url.includes("status=failed"))).toBe(true));
  expect(screen.getByRole("button", { name: "Waiting for you" })).toBeDisabled();
});

test("an empty history offers a first run", async () => {
  mockApi({ "/meta": META, "/runs": [], "/connectors": CONNECTORS });
  renderAt("/runs");
  expect(await screen.findByText("No runs yet")).toBeInTheDocument();
  for (const link of screen.getAllByRole("link", { name: /Start a run/ })) expect(link).toHaveAttribute("href", "/live");
});
