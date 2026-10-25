// "Add to code" (D44): the box puts the key into the app with one click; nothing to copy, no command to run.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { DEPS } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

const FAKE = "sk_test_FAKEFAKE12345678";
const spot = (name: string, kind: string, ref: string, sink: string | null, why_not: string | null = null) =>
  ({ name, kind, ref, sink, why_not, check: "abc123", where: sink === "dart-defines" ? "your Run config" : sink });
const MISSING = { name: "SUPABASE_ANON_KEY", status: "missing", ref: "lib/dev/app_config.dart:8", deps: [], command: "x",
  spot: spot("SUPABASE_ANON_KEY", "reads", "lib/dev/app_config.dart:8", "dart-defines"), in_app: false };
const OPEN = { name: "STRIPE_KEY", status: "missing", ref: "lib/pay.dart:3", deps: [], command: "x",
  spot: spot("STRIPE_KEY", "open", "lib/pay.dart:3", "dart-defines"), in_app: false };
const SAVED_NOT_IN_APP = { name: "MAPS_KEY", status: "saved", ref: "lib/maps.dart:2", deps: [], command: null,
  spot: spot("MAPS_KEY", "placeholder", "lib/maps.dart:2", "dart-defines"), in_app: false };
const NO_FILE = { name: "OPENAI_API_KEY", status: "missing", ref: "tool.py:2", deps: [], command: "x",
  spot: spot("OPENAI_API_KEY", "reads", "tool.py:2", null, "This app can't take keys from a file: it doesn't load .env."),
  in_app: false };
const CHANGED = ["lib/dev/app_config.dart:8", ".flowforge/dart-defines.json", "Run config (main_dart.xml)", "Vault"];

function keysApi(example = false) {
  const added = new Set<string>();
  const keys = () => [MISSING, OPEN, SAVED_NOT_IN_APP, NO_FILE]
    .map((k) => added.has(k.name) ? { ...k, status: "saved", in_app: true, command: null } : k);
  const route = (name: string) => () => { added.add(name); return { name, ref: "x", changed: CHANGED }; };
  return mockApi({
    "/meta": { ...META, example }, "/flow": DEPS, "/connectors": [], "/security": { findings: [] },
    "/keys": () => ({ repo: "travel", example, summary: {}, keys: keys() }),
    "/keys/SUPABASE_ANON_KEY/add-to-code": route("SUPABASE_ANON_KEY"),
    "/keys/STRIPE_KEY/add-to-code": route("STRIPE_KEY"),
    "/keys/MAPS_KEY/add-to-code": route("MAPS_KEY"),
    "/keys/OPENAI_API_KEY": () => { added.add("OPENAI_API_KEY"); return { name: "OPENAI_API_KEY", status: "saved" }; },
  });
}

const row = (name: string) => screen.getByText(name).closest("li")!;
const body = (calls: { url: string; init?: RequestInit }[], url: string) =>
  JSON.parse(String(calls.find((c) => c.url === url)?.init?.body));

test("paste a key, press Add to code: it goes into the app, the box clears, and nothing is left to copy", async () => {
  const calls = keysApi();
  renderAt("/keys");
  const box = await screen.findByLabelText("Value of SUPABASE_ANON_KEY");
  expect(within(row("SUPABASE_ANON_KEY")).getByText("lib/dev/app_config.dart:8")).toBeInTheDocument();
  await userEvent.type(box, FAKE);
  await userEvent.click(within(row("SUPABASE_ANON_KEY")).getByRole("button", { name: /Add to code/ }));
  expect(body(calls, "/keys/SUPABASE_ANON_KEY/add-to-code")).toEqual({ value: FAKE, ref: "lib/dev/app_config.dart:8", check: "abc123" });
  expect(await screen.findByText(/is in your app: .*Run config/)).toBeInTheDocument();
  expect(screen.getByText(/Press Run as always/)).toBeInTheDocument();
  expect(document.body.innerHTML).not.toContain(FAKE);
  expect(document.body.textContent).not.toMatch(/<how you start|Copy the start command/);
});

test("a key written in the open is hidden with one click, with nothing to type", async () => {
  const calls = keysApi();
  renderAt("/keys");
  await screen.findByText("STRIPE_KEY");
  expect(within(row("STRIPE_KEY")).getByText("open in code")).toBeInTheDocument();
  expect(within(row("STRIPE_KEY")).queryByLabelText("Value of STRIPE_KEY")).not.toBeInTheDocument();
  await userEvent.click(within(row("STRIPE_KEY")).getByRole("button", { name: /Hide it/ }));
  expect(body(calls, "/keys/STRIPE_KEY/add-to-code")).toEqual({ ref: "lib/pay.dart:3", check: "abc123" });
  expect(await screen.findByText(/is in your app/)).toBeInTheDocument();
});

test("a key saved before goes into the app with one click, with no retyping", async () => {
  const calls = keysApi();
  renderAt("/keys");
  await screen.findByText("SUPABASE_ANON_KEY");
  await userEvent.click(screen.getByText(/saved · MAPS_KEY/));   // the saved ones are folded
  expect(within(row("MAPS_KEY")).getByText("not in your app yet")).toBeInTheDocument();
  await userEvent.click(within(row("MAPS_KEY")).getByRole("button", { name: /Add to code/ }));
  expect(body(calls, "/keys/MAPS_KEY/add-to-code")).toEqual({ ref: "lib/maps.dart:2", check: "abc123" });
});

test("an app that reads no file gets Save, and one line saying why", async () => {
  const calls = keysApi();
  renderAt("/keys");
  const box = await screen.findByLabelText("Value of OPENAI_API_KEY");
  expect(within(row("OPENAI_API_KEY")).queryByRole("button", { name: /Add to code/ })).not.toBeInTheDocument();
  expect(within(row("OPENAI_API_KEY")).getByText(/doesn't load .env/)).toBeInTheDocument();
  await userEvent.type(box, FAKE);
  await userEvent.click(within(row("OPENAI_API_KEY")).getByRole("button", { name: /Save/ }));
  expect(calls.find((c) => c.url === "/keys/OPENAI_API_KEY")?.init?.method).toBe("PUT");
});

test("example data never adds to code", async () => {
  keysApi(true);
  renderAt("/keys");
  await screen.findByLabelText("Value of SUPABASE_ANON_KEY");
  expect(screen.queryByRole("button", { name: /Add to code|Hide it/ })).not.toBeInTheDocument();
});
