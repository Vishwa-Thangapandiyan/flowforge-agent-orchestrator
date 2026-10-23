import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";

afterEach(() => vi.unstubAllGlobals());

test("the rail has three places: the map, its checks and your coding agent (D33)", async () => {
  mockApi({ "/meta": META });
  renderAt("/checks");
  const nav = screen.getByRole("navigation", { name: "Main" });
  const links = Array.from(nav.querySelectorAll("a.rail-item")).map((a) => a.textContent);
  expect(links).toEqual(["Map", "Checks", "Connect agent"]);
  expect(screen.getByRole("link", { name: /Checks/ })).toHaveAttribute("aria-current", "page");
  for (const gone of ["Security", "Connectors", "Add app", "Approvals"]) expect(nav).not.toHaveTextContent(gone);
});

test("security has no page of its own: its old address opens the map", async () => {
  mockApi({ "/meta": META });
  renderAt("/security");
  expect(await screen.findByRole("link", { name: /Map/ })).toHaveAttribute("aria-current", "page");
});

test("API calls ask for JSON, never HTML", async () => {
  const calls = mockApi({ "/meta": META });
  renderAt("/checks");
  await vi.waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(new Headers(calls[0].init?.headers).get("Accept")).toBe("application/json");
});
