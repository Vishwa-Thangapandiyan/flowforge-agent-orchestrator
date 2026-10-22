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

test("the Security page counts findings by level and shows each with its masked lines, fix and prompt", async () => {
  const copied: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { copied.push(t); } } });
  mockApi({ "/meta": META, "/security": SECURITY });
  renderAt("/security");
  expect(await screen.findByRole("heading", { level: 1, name: "Security" })).toBeInTheDocument();
  expect(screen.getByText(/not everything/)).toBeInTheDocument();
  const counts = screen.getByRole("list", { name: "Findings by level" });
  expect(within(counts).getAllByRole("listitem").map((c) => c.textContent)).toEqual(["high1", "medium1", "low0"]);
  const card = screen.getByRole("heading", { name: KEY_FINDING.title }).closest("li")!;
  expect(within(card).getByText("config.py:23")).toBeInTheDocument();
  expect(card.querySelector(".hl")).toHaveTextContent('23GOOGLE_STATIC_MAPS_KEY = "[REDACTED]"');
  expect(within(card).getByText(/Then replace the key/)).toBeInTheDocument();
  await userEvent.click(within(card).getByRole("button", { name: /Copy prompt/ }));
  expect(copied).toEqual([KEY_FINDING.prompt]);
  expect(within(card).getByRole("link", { name: /Show on map/ })).toHaveAttribute("href", "/?focus=api-nominatim");
  // a finding that belongs to no dependency has nothing to show on the map
  const http = screen.getByRole("heading", { name: HTTP_FINDING.title }).closest("li")!;
  expect(within(http).queryByRole("link", { name: /Show on map/ })).not.toBeInTheDocument();
});

test("nothing found, and nothing scanned yet, each say so", async () => {
  mockApi({ "/meta": META, "/security": { repo: "trip-planner", scanned: true, summary: {}, findings: [] } });
  renderAt("/security");
  expect(await screen.findByText("Nothing found in trip-planner")).toBeInTheDocument();
});

test("before a scan the page asks for one", async () => {
  mockApi({ "/meta": META, "/security": { repo: null, scanned: false, summary: {}, findings: [] } });
  renderAt("/security");
  expect(await screen.findByText("Scan a folder first")).toBeInTheDocument();
});

test("a block with a finding wears a badge, and Show on map opens it with its findings", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/?focus=api-nominatim");
  const block = await screen.findByLabelText(/^Nominatim.*high security finding/, {}, { timeout: 6000 });
  expect(block.querySelector(".ff-risk.lv-high")).toBeInTheDocument();
  const panel = await screen.findByRole("heading", { level: 2, name: "Nominatim" }, { timeout: 6000 });
  const section = panel.closest("aside, section, div.sp")!.parentElement!;
  expect(within(section).getByText(KEY_FINDING.title)).toBeInTheDocument();
  expect(within(section).getByRole("link", { name: "The fix" })).toHaveAttribute("href", `/security#${KEY_FINDING.id}`);
}, 20000);
