import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { DEPS } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

export const KEY_FINDING = {
  id: "key_in_code-config-py-23", kind: "key_in_code", level: "high", title: "A Google API key is written in the code",
  ref: "config.py:23", line: 23, dep_id: "api-nominatim", first_line: 22,
  excerpt: ["# map image for the day", 'GOOGLE_STATIC_MAPS_KEY = "[REDACTED]"', 'STATIC_MAP_URL = "https://maps.googleapis.com/x"'],
  fix: "Move it to .env and read it from the environment. Then replace the key: it may be in your git history.",
  prompt: "In config.py:23, a Google API key is written in the code. Move it to an environment variable named GOOGLE_STATIC_MAPS_KEY.",
};
const HTTP_FINDING = {
  id: "plain_http-config-py-18", kind: "plain_http", level: "medium", title: "ip-api.com is called over http://",
  ref: "config.py:18", line: 18, dep_id: null, first_line: 18, excerpt: ['IP_API_URL = "http://ip-api.com/json/"'],
  fix: "Use https:// if the service offers it.", prompt: "Change it to https.",
};
export const SECURITY = { repo: "trip-planner", scanned: true, summary: { high: 1, medium: 1 }, findings: [KEY_FINDING, HTTP_FINDING] };

test("the map's warning chip lists what to fix, copies the fix prompt, and shows the block", async () => {
  const copied: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { copied.push(t); } } });
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/");
  const chip = await screen.findByRole("button", { name: /2 to fix/ }, { timeout: 6000 });
  await userEvent.click(chip);
  const list = screen.getByRole("dialog", { name: "To fix" });
  const rows = within(list).getAllByRole("listitem");
  expect(rows.map((r) => r.textContent)).toEqual([
    expect.stringContaining(`${KEY_FINDING.title}config.py:23`), expect.stringContaining(`${HTTP_FINDING.title}config.py:18`)]);
  expect(list).toHaveTextContent("Values are never shown");
  await userEvent.click(within(rows[0]).getByRole("button", { name: /Copy fix/ }));
  expect(copied).toEqual([KEY_FINDING.prompt]);
  expect(within(rows[1]).queryByRole("button", { name: "Show" })).not.toBeInTheDocument();   // belongs to no block
  await userEvent.click(within(rows[0]).getByRole("button", { name: "Show" }));
  const panel = await screen.findByRole("heading", { level: 2, name: "Nominatim" }, { timeout: 6000 });
  const aside = panel.closest("aside")!;
  expect(within(aside).getByRole("region", { name: "To fix" })).toHaveTextContent(KEY_FINDING.title);
  await userEvent.click(within(aside).getByRole("button", { name: /Copy fix prompt/ }));
  expect(copied[1]).toBe(KEY_FINDING.prompt);
}, 20000);

test("a block with a finding wears a badge; with nothing to fix there is no chip", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/");
  const block = await screen.findByLabelText(/^Nominatim.*high security finding/, {}, { timeout: 6000 });
  expect(block.querySelector(".ff-risk.lv-high")).toBeInTheDocument();
}, 20000);

test("nothing to fix: no chip at all", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": { ...SECURITY, summary: {}, findings: [] } });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" }, { timeout: 6000 });
  expect(screen.queryByRole("button", { name: /to fix/ })).not.toBeInTheDocument();
}, 20000);

test("/?focus=<dependency> still opens that block", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/?focus=api-nominatim");
  expect(await screen.findByRole("heading", { level: 2, name: "Nominatim" }, { timeout: 6000 })).toBeInTheDocument();
}, 20000);
