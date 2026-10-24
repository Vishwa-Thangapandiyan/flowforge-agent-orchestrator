import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { StepPanel } from "../flowmap/StepPanel";
import { META, mockApi, renderAt } from "../test/api";
import { DEPS } from "../test/flowFixture";
import type { KeyInfo } from "./Keys";

afterEach(() => vi.unstubAllGlobals());

const FAKE = "sk_test_FAKEFAKE12345678";
const MISSING = { name: "NOMINATIM_TOKEN", status: "missing", ref: "places.py:4", deps: ["api-nominatim"], command: "x" };
const IN_ENV = { name: "OLLAMA_API_KEY", status: "env_file", ref: "llm.py:3", deps: ["llm-ollama"], command: "x" };
const SAVED = { name: "WIKI_TOKEN", status: "saved", ref: "wiki.py:2", deps: ["api-wikipedia"], command: null };
const UNREADABLE = { name: "OLD_SECRET", status: "unreadable", ref: "old.py:1", deps: [], command: "x" };

/** A /keys that answers with what was saved so far, and every call it got. */
function keysApi(example = false) {
  const saved = new Set<string>();
  const removed = new Set<string>();
  const keys = () => [MISSING, IN_ENV, SAVED, UNREADABLE]
    .filter((k) => !removed.has(k.name))
    .map((k) => saved.has(k.name) ? { ...k, status: "saved", command: null } : k);
  const calls = mockApi({
    "/meta": { ...META, example }, "/flow": DEPS, "/connectors": [], "/security": { findings: [] },
    "/keys": () => ({ repo: "trip", example, summary: {}, keys: keys(), run: "flowforge run --repo /home/me/trip --" }),
    "/keys/NOMINATIM_TOKEN": (init?: RequestInit) => { saved.add("NOMINATIM_TOKEN"); return { name: "NOMINATIM_TOKEN", status: init?.method }; },
    "/keys/OLLAMA_API_KEY/import": () => { saved.add("OLLAMA_API_KEY"); return { name: "OLLAMA_API_KEY", status: "saved" }; },
    "/keys/WIKI_TOKEN": () => { removed.add("WIKI_TOKEN"); return { name: "WIKI_TOKEN", removed: true }; },
  });
  return calls;
}

const row = (name: string) => screen.getByText(name).closest("li")!;

test("each key has the one thing that fixes it, and nothing to copy", async () => {
  keysApi();
  renderAt("/keys");
  expect(await screen.findByRole("heading", { level: 1, name: "Keys" })).toBeInTheDocument();
  await screen.findByText("NOMINATIM_TOKEN");
  expect(within(row("NOMINATIM_TOKEN")).getByLabelText("Value of NOMINATIM_TOKEN")).toBeInTheDocument();   // open already
  expect(within(row("OLLAMA_API_KEY")).getByRole("button", { name: "Move into FlowForge" })).toBeInTheDocument();
  expect(within(row("WIKI_TOKEN")).getByRole("button", { name: "Replace" })).toBeInTheDocument();
  expect(within(row("OLD_SECRET")).getByText("can't read")).toBeInTheDocument();
  expect(within(row("OLD_SECRET")).getByLabelText("Value of OLD_SECRET")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Copy command/ })).not.toBeInTheDocument();
  expect(screen.getByText("2 missing")).toBeInTheDocument();
});

test("a pasted key is sent once, cleared at once, and never shown", async () => {
  const calls = keysApi();
  renderAt("/keys");
  const box = await screen.findByLabelText("Value of NOMINATIM_TOKEN");
  expect(box).toHaveAttribute("type", "password");
  expect(box).toHaveAttribute("autocomplete", "off");
  await userEvent.type(box, FAKE);
  await userEvent.click(within(row("NOMINATIM_TOKEN")).getByRole("button", { name: /Save/ }));
  const put = calls.find((c) => c.url === "/keys/NOMINATIM_TOKEN");
  expect(put?.init?.method).toBe("PUT");
  expect(JSON.parse(String(put?.init?.body))).toEqual({ value: FAKE });
  expect(await screen.findByText(/saved · .*NOMINATIM_TOKEN/)).toBeInTheDocument();   // folded with the saved ones
  expect(screen.queryByLabelText("Value of NOMINATIM_TOKEN")).not.toBeInTheDocument();
  expect(document.body.innerHTML).not.toContain(FAKE);
});

test("a key in .env moves in with one click", async () => {
  const calls = keysApi();
  renderAt("/keys");
  await userEvent.click(await screen.findByRole("button", { name: "Move into FlowForge" }));
  expect(calls.find((c) => c.url === "/keys/OLLAMA_API_KEY/import")?.init?.method).toBe("POST");
  expect(await screen.findByText(/saved · .*OLLAMA_API_KEY/)).toBeInTheDocument();
});

test("a saved key can be replaced or removed", async () => {
  const calls = keysApi();
  renderAt("/keys");
  await userEvent.click(await screen.findByText(/1 saved · WIKI_TOKEN/));   // the saved ones are folded
  await userEvent.click(await screen.findByRole("button", { name: "Replace" }));
  expect(within(row("WIKI_TOKEN")).getByLabelText("Value of WIKI_TOKEN")).toBeInTheDocument();
  await userEvent.click(within(row("WIKI_TOKEN")).getByRole("button", { name: "Cancel" }));
  await userEvent.click(within(row("WIKI_TOKEN")).getByRole("button", { name: "Remove" }));
  expect(calls.find((c) => c.url === "/keys/WIKI_TOKEN")?.init?.method).toBe("DELETE");
  await vi.waitFor(() => expect(screen.queryByText("WIKI_TOKEN")).not.toBeInTheDocument());
});

test("example data saves keys too, so the demo works", async () => {
  keysApi(true);
  renderAt("/keys");
  expect(await screen.findByLabelText("Value of NOMINATIM_TOKEN")).toBeInTheDocument();
});

test("blocks wear a key badge until their keys are saved", async () => {
  keysApi();
  renderAt("/");
  expect(await screen.findByLabelText(/^Nominatim, .*key missing/)).toBeInTheDocument();
  expect(screen.getByLabelText(/^Ollama, .*key only in \.env/)).toBeInTheDocument();
  expect(screen.getByLabelText(/^Wikipedia, /).getAttribute("aria-label")).not.toMatch(/key/);   // saved: no badge
});

test("the step panel lists the block's keys with the same box", () => {
  mockApi({});
  const node = DEPS.nodes.find((n) => n.id === "api-nominatim")!;
  const actions = { close: vi.fn(), approve: vi.fn(), reject: vi.fn(), edit: vi.fn(async () => {}), reset: vi.fn(async () => {}),
    dismissTip: vi.fn() };
  render(<MemoryRouter><StepPanel node={node} flow={DEPS} tile={null} state="idle" cap="" waiting={false} connectors={[]} tipShown
    layer="mine" actions={actions} keys={[MISSING as KeyInfo]} /></MemoryRouter>);
  const keys = screen.getByRole("region", { name: "Keys" });
  expect(within(keys).getByText("NOMINATIM_TOKEN")).toBeInTheDocument();
  expect(within(keys).getByRole("link", { name: /Add the key/ })).toHaveAttribute("href", "/keys?key=NOMINATIM_TOKEN");   // D38
  expect(within(keys).getByLabelText("Value of NOMINATIM_TOKEN")).toHaveAttribute("type", "password");
});

test("what your agent asked for comes first, with why, and ?key= puts you in its box", async () => {
  mockApi({
    "/meta": META, "/flow": DEPS, "/connectors": [], "/security": { findings: [] },
    "/keys": { repo: "trip", example: false, summary: {}, run: "flowforge run --",
      requests: [{ name: "STRIPE_SECRET_KEY", why: "for Stripe in pay.py", at: new Date().toISOString() }],
      keys: [{ name: "STRIPE_SECRET_KEY", status: "missing", ref: null, deps: ["api-stripe"], command: "x", requested: true }, MISSING] },
  });
  renderAt("/keys?key=STRIPE_SECRET_KEY");
  const wait = await screen.findByRole("region", { name: "Your agent is waiting for" });
  expect(wait).toHaveTextContent(/STRIPE_SECRET_KEY.*for Stripe in pay\.py · asked just now/);
  await vi.waitFor(() => expect(document.activeElement).toBe(within(wait).getByLabelText("Value of STRIPE_SECRET_KEY")));
  expect(screen.getByRole("link", { name: /See your keys in the Vault/ })).toHaveAttribute("href", "/vault");
});

test("the map says when your agent asked for a key, with a way to review its change and to add it", async () => {
  mockApi({
    "/meta": META, "/flow": DEPS, "/connectors": [], "/security": { findings: [] },
    "/keys": { repo: "trip", example: false, summary: {}, requests: [{ name: "STRIPE_SECRET_KEY", why: "for Stripe", at: "2026-10-24T10:00:00Z" }],
      keys: [] },
  });
  renderAt("/");
  expect(await screen.findByText(/Your agent asked for STRIPE_SECRET_KEY/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Add the key" })).toHaveAttribute("href", "/keys?key=STRIPE_SECRET_KEY");
  expect(screen.getByRole("button", { name: "Review its change" })).toBeInTheDocument();
});
