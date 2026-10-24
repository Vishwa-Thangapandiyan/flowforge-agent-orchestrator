import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const FAKE = "sk_live_FAKEFAKE12345678";
const QR = { uri: "otpauth://totp/FlowForge:key%20view?secret=JBSWY3DPEHPK3PXP&issuer=FlowForge", qr: "data:image/svg+xml;base64,PHN2Zy8+" };
const VAULT = { keys: [
  { name: "STRIPE_SECRET_KEY", places: [{ where: "saved", ref: null, store: "keychain" }], added: "2026-10-24T10:00:00+00:00",
    kind: "live", deps: [{ id: "api-stripe", name: "Stripe" }], ref: "pay.py:5", health: ["healthy"] },
  { name: "GOOGLE_KEY", places: [{ where: "code", ref: "pay.py:4", store: null }], added: null, kind: null,
    deps: [{ id: "api-gm", name: "Google Maps" }], ref: "pay.py:4", health: ["in code"] },
  { name: "OPENAI_API_KEY", places: [{ where: "env", ref: ".env", store: null }], added: null, kind: "test", deps: [], ref: "ai.py:4",
    health: ["in .env"] },
  { name: "OLD_TOKEN", places: [{ where: "saved", ref: null, store: "file" }], added: "2026-03-02T10:00:00+00:00", kind: null,
    deps: [], ref: null, health: ["unused"] },
  { name: "NOT_SAVED_TOKEN", places: [], added: null, kind: null, deps: [], ref: "pay.py:8", health: ["missing"] },
] };

function vaultApi(start: "none" | "on" | "open", resetAt: string | null = null) {
  let state = start;
  let ticket = false;
  return mockApi({
    "/meta": META, "/issues": { repo: "trip", example: false, summary: {}, issues: [] },
    "/keys": { repo: "trip", example: false, summary: {}, keys: [] },
    "/lock": () => ({ state: state === "open" ? "on" : state, open: state === "open", seconds_left: state === "open" ? 300 : 0, reset_at: resetAt }),
    "/lock/setup": QR,
    "/lock/confirm": () => { state = "on"; return { state: "on" }; },
    "/lock/password": (init?: RequestInit) => {
      if (JSON.parse(String(init?.body)).password !== "correct horse") return new Response(JSON.stringify({ detail: "Wrong password." }), { status: 403 });
      ticket = true;
      return { next: "code" };
    },
    "/lock/code": () => {
      if (!ticket) return new Response(JSON.stringify({ detail: "Type your password first." }), { status: 403 });
      state = "open";
      return { open: true, seconds_left: 300 };
    },
    "/lock/close": () => { state = "on"; return { open: false }; },
    "/vault/keys": VAULT,
    "/keys/reveal": { value: FAKE },
    "/keys/OPENAI_API_KEY/import": { name: "OPENAI_API_KEY", status: "saved" },
    "/keys/OLD_TOKEN": { name: "OLD_TOKEN", removed: true },
  });
}

test("first time: a three-step set-up, password, QR, code", async () => {
  const calls = vaultApi("none");
  renderAt("/vault");
  expect(await screen.findByText("Step 1 of 3")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Password"), "correct horse");
  await userEvent.type(screen.getByLabelText("Password again"), "correct horse");
  await userEvent.click(screen.getByRole("button", { name: /Next/ }));
  expect(await screen.findByRole("img", { name: /QR code/ })).toHaveAttribute("src", QR.qr);
  expect(screen.getByText("Step 2 of 3")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Code from your phone"), "482917");
  await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
  expect(JSON.parse(String(calls.find((c) => c.url === "/lock/confirm")?.init?.body))).toEqual({ password: "correct horse", code: "482917" });
  expect(await screen.findByText("Step 1 of 2 · your password")).toBeInTheDocument();   // straight to opening it
});

test("open: the password on one screen, then the code on the next", async () => {
  const calls = vaultApi("on");
  renderAt("/vault");
  expect(await screen.findByText("Step 1 of 2 · your password")).toBeInTheDocument();
  expect(screen.queryByLabelText("Code from your phone")).not.toBeInTheDocument();   // one at a time
  await userEvent.type(screen.getByLabelText("Password"), "correct horse");
  await userEvent.click(screen.getByRole("button", { name: /Next/ }));
  expect(await screen.findByText("Step 2 of 2 · the code on your phone")).toBeInTheDocument();
  expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Code from your phone"), "482917");
  await userEvent.click(screen.getByRole("button", { name: "Unlock" }));
  expect(calls.filter((c) => c.url.startsWith("/lock/")).map((c) => c.url)).toEqual(["/lock/password", "/lock/code"]);
  expect(await screen.findByText("STRIPE_SECRET_KEY")).toBeInTheDocument();
});

test("a wrong password stays on step one and says so", async () => {
  vaultApi("on");
  renderAt("/vault");
  await userEvent.type(await screen.findByLabelText("Password"), "wrong password");
  await userEvent.click(screen.getByRole("button", { name: /Next/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Wrong password");
  expect(screen.getByText("Step 1 of 2 · your password")).toBeInTheDocument();
});

test("open: every key with its health, where it lives, what uses it, and the action that fixes it", async () => {
  vaultApi("open");
  renderAt("/vault");
  const row = async (name: string) => (await screen.findByText(name, { selector: ".vt-name" })).closest("tr")!;
  expect(await row("STRIPE_SECRET_KEY")).toHaveTextContent(/✓ healthy.*keychain.*Stripe.*live/);
  expect(within(await row("GOOGLE_KEY")).getByRole("link", { name: "Fix" })).toHaveAttribute("href", "/p/test/issues");
  expect(within(await row("OPENAI_API_KEY")).getByRole("button", { name: "Move in" })).toBeInTheDocument();
  expect(within(await row("OLD_TOKEN")).getByRole("button", { name: "Remove" })).toBeInTheDocument();
  expect(within(await row("NOT_SAVED_TOKEN")).getByRole("link", { name: "Add" })).toHaveAttribute("href", "/p/test/keys?key=NOT_SAVED_TOKEN");
  expect(screen.getByText("written in code").previousSibling).toHaveTextContent("1");
  expect(document.body.innerHTML).not.toContain(FAKE);
});

test("Show reveals one value, then it hides after 30 seconds", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const calls = vaultApi("open");
  renderAt("/vault");
  const row = (await screen.findByText("STRIPE_SECRET_KEY", { selector: ".vt-name" })).closest("tr")!;
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await user.click(within(row).getByRole("button", { name: "Show" }));
  expect(await within(row).findByText(FAKE)).toBeInTheDocument();
  expect(JSON.parse(String(calls.find((c) => c.url === "/keys/reveal")?.init?.body))).toEqual({ where: "saved", name: "STRIPE_SECRET_KEY", ref: null });
  await act(async () => { vi.advanceTimersByTime(31_000); });
  expect(document.body.innerHTML).not.toContain(FAKE);
});

test("Lock now closes it, and a forced reset is shown", async () => {
  const calls = vaultApi("open", "2026-10-24T14:02:00+00:00");
  renderAt("/vault");
  expect(await screen.findByRole("alert")).toHaveTextContent("lock was reset");
  await userEvent.click(await screen.findByRole("button", { name: "Lock now" }));
  expect(calls.find((c) => c.url === "/lock/close")?.init?.method).toBe("POST");
  expect(await screen.findByText("Step 1 of 2 · your password")).toBeInTheDocument();
});
