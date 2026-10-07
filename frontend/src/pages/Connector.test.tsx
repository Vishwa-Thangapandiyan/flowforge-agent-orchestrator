import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS, HEALTH, connector } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

const RAZORPAY = { ...CONNECTORS[0], slot: "payments", rate_limit_rpm: 60 };
const ACTIVITY = [
  { run_id: "r1", plan: "Payment risk check", step_id: "payment", title: "Fetch the captured payment", state: "succeeded", error: null, cache_hit: false,
    attempts: 1, duration_ms: 800, at: "2026-10-07T12:04:00Z" },
];

test("the zoom panel shows the connection, never a key value, and recent activity", async () => {
  mockApi({ "/meta": META, "/connectors/razorpay": RAZORPAY, "/health/tools": HEALTH, "/connectors/razorpay/activity": ACTIVITY });
  renderAt("/connectors/razorpay");
  expect(await screen.findByRole("heading", { name: "Razorpay", level: 1 })).toBeInTheDocument();
  const conn = screen.getByRole("region", { name: "Connection" });
  expect(within(conn).getByText("example (no key)")).toBeInTheDocument();
  expect(within(conn).getByText("env:RAZORPAY_KEY")).toBeInTheDocument();
  expect(within(conn).getByText("58 of 60")).toBeInTheDocument();
  expect(screen.getByText("Connected · test mode")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Swap app" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Test connection" })).toBeDisabled(); // http testing is Phase 3
  const activity = screen.getByRole("region", { name: "Recent activity" });
  expect(within(activity).getByRole("link", { name: "Payment risk check" })).toHaveAttribute("href", "/runs/r1");
  expect(screen.getByRole("region", { name: "Suggested by the Planner" })).toHaveTextContent("Arrives in Phase 4");
});

test("a missing key says where to put it", async () => {
  const gemini = { ...CONNECTORS[1], secret_ref: "env:GEMINI_API_KEY", secret: { ref: "env:GEMINI_API_KEY", status: "missing" as const } };
  mockApi({ "/meta": { ...META, example: false }, "/connectors/gemini": gemini, "/health/tools": HEALTH, "/connectors/gemini/activity": [] });
  renderAt("/connectors/gemini");
  const conn = await screen.findByRole("region", { name: "Connection" });
  expect(within(conn).getByText("missing")).toBeInTheDocument();
  expect(conn).toHaveTextContent("GEMINI_API_KEY=");
  expect(conn).toHaveTextContent(".env");
});

test("testing a local app shows the answer; removing needs a second click", async () => {
  const py = connector({ id: "py", type: "local", name: "Python", connection: { command: ["python"], cwd: "." } });
  const calls = mockApi({
    "/meta": META, "/connectors/py": py, "/health/tools": HEALTH, "/connectors/py/activity": [], "/connectors": [],
    "/connectors/py/test": { ok: true, message: "Ready. The program and its folder were found." },
  });
  renderAt("/connectors/py");
  fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));
  expect(await screen.findByText("Ready. The program and its folder were found.")).toBeInTheDocument();
  const remove = screen.getByRole("button", { name: "Remove app" });
  fireEvent.click(remove);
  expect(screen.getByRole("button", { name: "Click again to remove" })).toBeInTheDocument();
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Click again to remove" }));
  await vi.waitFor(() => expect(calls.some((c) => c.init?.method === "DELETE" && c.url === "/connectors/py")).toBe(true));
});

test("apps from connectors.json can't be edited here", async () => {
  mockApi({ "/meta": META, "/connectors/razorpay": { ...RAZORPAY, managed_by: "file" }, "/health/tools": HEALTH,
    "/connectors/razorpay/activity": [] });
  renderAt("/connectors/razorpay");
  expect(await screen.findByText(/edit that file to change it/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Edit this form" })).not.toBeInTheDocument();
});
