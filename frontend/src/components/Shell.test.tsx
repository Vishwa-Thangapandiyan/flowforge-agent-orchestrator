import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";

afterEach(() => vi.unstubAllGlobals());

test("the nav lists every page, with later phases marked", async () => {
  mockApi({ "/meta": META });
  renderAt("/security");
  const nav = screen.getByRole("navigation", { name: "Main" });
  for (const name of ["Flow map", "Runs", "Connectors", "Approvals", "Security"]) {
    expect(nav).toHaveTextContent(name);
  }
  expect(screen.getByRole("link", { name: /Security/ })).toHaveAttribute("aria-current", "page");
  expect(nav).toHaveTextContent("Phase 4");
  expect(nav).toHaveTextContent("Phase 5");
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
