import { screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { viewsFor } from "../components/OutputViewer";
import { META, mockApi, renderAt } from "../test/api";
import { run } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

test("the output viewer picks the view that fits", () => {
  expect(viewsFor({ kind: "table", rows: [{ a: 1 }] })).toEqual(["table", "json"]);
  expect(viewsFor({ stdout: "ok" })).toEqual(["text", "json"]);
  expect(viewsFor({ content: "", blocks: [{ kind: "image", mime: "image/png", data_b64: "AA==" }] })).toEqual(["image", "json"]);
  expect(viewsFor({ status: 200, body: [{ id: 1 }] })).toEqual(["table", "json"]);
  expect(viewsFor(null)).toEqual(["json"]);
});

const step = (id: string, start: number, end: number, extra: object = {}) => ({
  step_id: id, state: "succeeded", output: null, error: null, attempts: 1, cache_hit: false,
  started_at: start, finished_at: end, call_ms: 1, answered_by: null, ...extra,
});

test("a finished run shows its bars, the slowest chain, totals and outputs", async () => {
  mockApi({
    "/meta": META,
    "/runs/r1": {
      status: "succeeded", error: null,
      summary: run({ id: "r1", status: "succeeded", plan: "Nightly finance check", time_ms: 4000 }),
      steps: [
        { id: "scan", title: "Scan the code", type: "local", connector: "sirius", depends_on: [] },
        { id: "pay", title: "Fetch payments", type: "http", connector: "razorpay", depends_on: [] },
        { id: "sum", title: "Write the summary", type: "llm", connector: "gemini", depends_on: ["scan", "pay"] },
      ],
      result: {
        workflow_id: "w", policy: "critical_path", status: "succeeded", makespan_ms: 4000, api_calls: 3, cache_hits: 1,
        predicted_critical_path: ["scan", "sum"], predicted_critical_path_ms: 9000,
        actual_critical_path: ["scan", "sum"], actual_critical_path_ms: 4000,
        steps: {
          scan: step("scan", 0, 3),
          pay: step("pay", 0, 1, { cache_hit: true, output: { kind: "table", rows: [{ payment: "pay_1", status: "captured" }] } }),
          sum: step("sum", 3, 4, { output: { text: "All good", usage: { prompt_tokens: 800, completion_tokens: 240 } } }),
        },
      },
    },
  });
  renderAt("/runs/r1");
  expect(await screen.findByRole("heading", { name: "Finished", level: 1 })).toBeInTheDocument();
  expect(screen.getByText("API calls · 1 skipped by cache")).toBeInTheDocument();
  expect(screen.getByText("1,040")).toBeInTheDocument(); // tokens from the summary step
  const bars = screen.getByRole("list", { name: "Who ran when" });
  expect(within(bars).getByRole("button", { name: /Scan the code.*: done, 3.0 s, on the slowest chain/ })).toBeInTheDocument();
  expect(within(bars).getByRole("button", { name: /Fetch payments.*: answered from cache/ })).toBeInTheDocument();
  within(bars).getByRole("button", { name: /Fetch payments/ }).click();
  const output = await screen.findByRole("region", { name: "Output of 2 Fetch payments" });
  expect(within(output).getByRole("table")).toHaveTextContent("captured");
});
