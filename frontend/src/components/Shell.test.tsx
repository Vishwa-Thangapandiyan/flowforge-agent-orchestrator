import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { ISSUES } from "../test/securityFixture";

afterEach(() => vi.unstubAllGlobals());

test("the rail has six places, then Settings at the bottom where Theme was (D38, D40)", async () => {
  mockApi({ "/meta": META });
  renderAt("/checks");
  const nav = screen.getByRole("navigation", { name: "Main" });
  const links = Array.from(nav.querySelectorAll("a.rail-item")).map((a) => a.textContent);
  expect(links).toEqual(["Map", "Issues", "Keys", "Vault", "Checks", "Connect agent", "Settings"]);
  expect(nav).not.toHaveTextContent("Theme");
  expect(screen.getByRole("link", { name: /Checks/ })).toHaveAttribute("aria-current", "page");
  for (const gone of ["Security", "Connectors", "Add app", "Approvals"]) expect(nav).not.toHaveTextContent(gone);
});

test("the rail counts what needs you, and the old security address opens Issues", async () => {
  mockApi({ "/meta": META, "/issues": ISSUES,
    "/keys": { repo: "trip-planner", example: false, summary: {}, keys: [
      { name: "OLLAMA_API_KEY", status: "missing", ref: "config.py:30", deps: [], command: null }] } });
  renderAt("/security");
  expect(await screen.findByRole("link", { name: /Issues/ })).toHaveAttribute("aria-current", "page");
  expect(await screen.findByLabelText("2 to fix")).toBeInTheDocument();
  expect(screen.getByLabelText("1 need you")).toBeInTheDocument();
});

test("API calls ask for JSON, never HTML", async () => {
  const calls = mockApi({ "/meta": META });
  renderAt("/checks");
  await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(new Headers(calls[0].init?.headers).get("Accept")).toBe("application/json");
});
