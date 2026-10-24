import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { DEPS } from "../test/flowFixture";
import { StepPanel } from "../flowmap/StepPanel";
import type { KeyInfo } from "./Keys";
import { SECURITY } from "../test/securityFixture";

afterEach(() => vi.unstubAllGlobals());

const FAKE = "sk_test_FAKEFAKE12345678";
const MISSING = { name: "NOMINATIM_TOKEN", status: "missing", ref: "places.py:4", deps: ["api-nominatim"],
  command: "flowforge key add NOMINATIM_TOKEN --repo /home/me/trip" };
const IN_ENV = { name: "OLLAMA_API_KEY", status: "env_file", ref: "llm.py:3", deps: ["llm-ollama"],
  command: "flowforge key import --repo /home/me/trip" };
const SAVED = { name: "WIKI_TOKEN", status: "saved", ref: "wiki.py:2", deps: ["api-wikipedia"], command: null };

function keysApi(example = false) {
  const keys = [MISSING, IN_ENV, SAVED];
  const saved: string[] = [];
  const routes = {
    "/meta": { ...META, example }, "/flow": DEPS, "/connectors": [], "/security": SECURITY,
    "/keys": () => ({ repo: "trip", example, summary: {}, keys: keys.map((k) => saved.includes(k.name) ? { ...k, status: "saved", command: null } : k) }),
    "/keys/NOMINATIM_TOKEN": (init?: RequestInit) => {
      saved.push("NOMINATIM_TOKEN");
      return { name: "NOMINATIM_TOKEN", status: "saved", sent: init?.method };
    },
  };
  return mockApi(routes);
}

test("the warning chip counts the keys FlowForge doesn't have, and copies the command that adds one", async () => {
  const copied: string[] = [];
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: async (t: string) => { copied.push(t); } } });
  keysApi();
  renderAt("/");
  await userEvent.click(await screen.findByRole("button", { name: /4 to fix/ }));   // 2 findings + 2 keys
  const keys = within(screen.getByRole("dialog", { name: "To fix" })).getByRole("region", { name: "Keys" });
  const rows = within(keys).getAllByRole("listitem");
  expect(rows.map((r) => r.textContent)).toEqual([
    expect.stringContaining("NOMINATIM_TOKENmissingplaces.py:4"), expect.stringContaining("OLLAMA_API_KEYin .envllm.py:3")]);
  await userEvent.click(within(rows[0]).getByRole("button", { name: /Copy command/ }));
  expect(copied).toEqual([MISSING.command]);
  expect(within(rows[1]).queryByRole("button", { name: "Add here" })).not.toBeInTheDocument();   // import it instead
});

test("a key pasted into the box is sent once, cleared at once, and never shown", async () => {
  const calls = keysApi();
  renderAt("/");
  await userEvent.click(await screen.findByRole("button", { name: /4 to fix/ }));
  await userEvent.click(screen.getByRole("button", { name: "Add here" }));
  const box = screen.getByLabelText("Value of NOMINATIM_TOKEN");
  expect(box).toHaveAttribute("type", "password");
  expect(box).toHaveAttribute("autocomplete", "off");
  await userEvent.type(box, FAKE);
  await userEvent.click(screen.getByRole("button", { name: /Save/ }));
  const put = calls.find((c) => c.url === "/keys/NOMINATIM_TOKEN");
  expect(put?.init?.method).toBe("PUT");
  expect(JSON.parse(String(put?.init?.body))).toEqual({ value: FAKE });
  expect(await screen.findByRole("button", { name: /3 to fix/ })).toBeInTheDocument();   // reloaded
  expect(screen.queryByLabelText("Value of NOMINATIM_TOKEN")).not.toBeInTheDocument();
  expect(document.body.innerHTML).not.toContain(FAKE);
  expect(calls.filter((c) => c.url !== "/keys/NOMINATIM_TOKEN").every((c) => !String(c.init?.body ?? "").includes(FAKE))).toBe(true);
});

test("blocks wear a key badge until their keys are saved", async () => {
  keysApi();
  renderAt("/");
  expect(await screen.findByLabelText(/^Nominatim, .*key missing/, {})).toBeInTheDocument();
  expect(screen.getByLabelText(/^Ollama, .*key only in \.env/)).toBeInTheDocument();
  expect(screen.getByLabelText(/^Wikipedia, /).getAttribute("aria-label")).not.toMatch(/key/);   // saved: no badge
});

test("the step panel lists the block's keys with the same box", async () => {
  mockApi({});
  const node = DEPS.nodes.find((n) => n.id === "api-nominatim")!;
  const actions = { close: vi.fn(), approve: vi.fn(), reject: vi.fn(), edit: vi.fn(async () => {}), reset: vi.fn(async () => {}),
    dismissTip: vi.fn() };
  render(<StepPanel node={node} flow={DEPS} tile={null} state="idle" cap="" waiting={false} connectors={[]} tipShown
    layer="mine" actions={actions} keys={[MISSING as KeyInfo]} />);
  const keys = screen.getByRole("region", { name: "Keys" });
  expect(within(keys).getByText("NOMINATIM_TOKEN")).toBeInTheDocument();
  await userEvent.click(within(keys).getByRole("button", { name: "Add here" }));
  expect(within(keys).getByLabelText("Value of NOMINATIM_TOKEN")).toHaveAttribute("type", "password");
});

test("example data shows the keys but has no box to save one", async () => {
  keysApi(true);
  renderAt("/");
  await userEvent.click(await screen.findByRole("button", { name: /4 to fix/ }));
  expect(screen.queryByRole("button", { name: "Add here" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: /Copy command/ })).toHaveLength(2);
});
