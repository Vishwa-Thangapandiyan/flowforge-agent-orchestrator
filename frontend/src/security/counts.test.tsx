import { act, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { CHECKS, DEPS, PLAN } from "../test/flowFixture";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const REAL = { ...META, example: false };
const STRIPE = { name: "STRIPE_SECRET_KEY", status: "missing", deps: ["api-stripe"], requested: true };

test("a key your agent asks for shows on the rail while you stay on the map (D38)", async () => {
  // Codex review: the badge only refreshed on a page change, so a request made while you watched the map stayed hidden
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let asked: string[] = [];
  const calls = mockApi({
    "/meta": REAL, "/flow": DEPS, "/connectors": CONNECTORS, "/checks": CHECKS, "/checks/plan": PLAN,
    "/issues": { repo: "shop", example: false, summary: {}, issues: [] },
    "/keys": () => ({ repo: "shop", example: false, summary: {}, keys: asked.length ? [STRIPE] : [], requests: [] }),
    "/keys/asked": () => ({ names: asked }),
  });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  expect(screen.queryByLabelText("1 need you")).not.toBeInTheDocument();

  asked = ["STRIPE_SECRET_KEY"];   // your agent calls request_key
  await act(async () => { vi.advanceTimersByTime(6_000); });
  expect(await screen.findByLabelText("1 need you")).toBeInTheDocument();

  const keyReads = calls.filter((c) => c.url.split("?")[0] === "/keys").length;
  await act(async () => { vi.advanceTimersByTime(20_000); });   // nothing new asked: the code isn't read again
  expect(calls.filter((c) => c.url.split("?")[0] === "/keys").length).toBe(keyReads);
});
