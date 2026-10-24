import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { DEPS } from "../test/flowFixture";
import { HTTP_FINDING, KEY_FINDING, SECURITY } from "../test/securityFixture";

afterEach(() => vi.unstubAllGlobals());


test("the map's warning chip lists what to fix, copies the fix prompt, and shows the block", async () => {
  const copied: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { copied.push(t); } } });
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/");
  const chip = await screen.findByRole("button", { name: /2 to fix/ });
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
  const panel = await screen.findByRole("heading", { level: 2, name: "Nominatim" });
  const aside = panel.closest("aside")!;
  expect(within(aside).getByRole("region", { name: "To fix" })).toHaveTextContent(KEY_FINDING.title);
  await userEvent.click(within(aside).getByRole("button", { name: /Copy fix prompt/ }));
  expect(copied[1]).toBe(KEY_FINDING.prompt);
}, 20000);

test("a block with a finding wears a badge; with nothing to fix there is no chip", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/");
  const block = await screen.findByLabelText(/^Nominatim.*high security finding/, {});
  expect(block.querySelector(".ff-risk.lv-high")).toBeInTheDocument();
}, 20000);

test("nothing to fix: no chip at all", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": { ...SECURITY, summary: {}, findings: [] } });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  expect(screen.queryByRole("button", { name: /to fix/ })).not.toBeInTheDocument();
}, 20000);

test("/?focus=<dependency> still opens that block", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/?focus=api-nominatim");
  expect(await screen.findByRole("heading", { level: 2, name: "Nominatim" })).toBeInTheDocument();
}, 20000);
