import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { FLOW, PENDING } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

test("re-check shows each change and saves only what you pick", async () => {
  let accepted: unknown;
  mockApi({
    "/meta": META, "/flow": { ...FLOW, pending: 2 }, "/flow/versions/2": PENDING, "/connectors": CONNECTORS,
    "/flow/versions/2/accept": (init?: RequestInit) => {
      accepted = JSON.parse(String(init?.body));
      return { ...FLOW, version: 2 };
    },
  });
  renderAt("/map/recheck");
  expect(await screen.findByText("New: Refund received")).toBeInTheDocument();
  expect(screen.getByText("Needs you")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Use the Planner's" }));
  await userEvent.click(screen.getByRole("button", { name: "Keep it" }));
  await userEvent.click(screen.getByRole("button", { name: /Save as map v2/ }));
  await vi.waitFor(() => expect(accepted).toEqual({ take: { c1: true, c2: "planner", c3: false } }));
});

test("with nothing pending there is nothing to review", async () => {
  mockApi({ "/meta": META, "/flow": FLOW, "/connectors": CONNECTORS });
  renderAt("/map/recheck");
  expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
});
