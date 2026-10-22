import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";

afterEach(() => vi.unstubAllGlobals());

test("the nav lists every page, with later phases marked", async () => {
  mockApi({ "/meta": META });
  renderAt("/security");
  const nav = screen.getByRole("navigation", { name: "Main" });
  for (const name of ["Flow map", "Checks", "Connectors", "Security"]) {
    expect(nav).toHaveTextContent(name);
  }
  // Runs became Checks (D24); Approvals waits for V2 (D19)
  expect(nav).not.toHaveTextContent("Approvals");
  expect(screen.getByRole("link", { name: /Security/ })).toHaveAttribute("aria-current", "page");
  expect(nav).not.toHaveTextContent("Phase 7");   // findings are real since D31
});

test("example data is labelled as such", async () => {
  mockApi({ "/meta": META });
  renderAt("/security");
  expect(await screen.findByText("Example data.")).toBeInTheDocument();
});

test("no example banner with real data", async () => {
  const calls = mockApi({ "/meta": { ...META, example: false } });
  renderAt("/security");
  await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(screen.queryByText("Example data.")).not.toBeInTheDocument();
});

test("API calls ask for JSON, never HTML", async () => {
  const calls = mockApi({ "/meta": META });
  renderAt("/security");
  await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(new Headers(calls[0].init?.headers).get("Accept")).toBe("application/json");
});
