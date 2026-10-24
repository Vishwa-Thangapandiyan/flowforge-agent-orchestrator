import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { DEPS } from "../test/flowFixture";
import { ISSUES, SECURITY } from "../test/securityFixture";

afterEach(() => vi.unstubAllGlobals());


test("the map's warning chip counts what needs you and opens the Issues page", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY, "/issues": ISSUES });
  renderAt("/");
  const chip = await screen.findByRole("link", { name: /^\s*2 to fix$/ });
  expect(chip).toHaveClass("lv-high");
  await userEvent.click(chip);
  expect(await screen.findByRole("heading", { level: 1, name: "Issues" })).toBeInTheDocument();
});

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
  expect(screen.queryByRole("link", { name: /to fix/ })).not.toBeInTheDocument();
}, 20000);

test("/?focus=<dependency> still opens that block", async () => {
  mockApi({ "/meta": META, "/flow": DEPS, "/connectors": [], "/security": SECURITY });
  renderAt("/?focus=api-nominatim");
  expect(await screen.findByRole("heading", { level: 2, name: "Nominatim" })).toBeInTheDocument();
}, 20000);
