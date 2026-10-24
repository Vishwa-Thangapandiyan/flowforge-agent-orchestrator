import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const FAKE = "sk_test_FAKEFAKE12345678";
const KEYS = { repo: "trip", example: false, summary: {}, run: "flowforge run --", keys: [
  { name: "STRIPE_KEY", status: "saved", ref: "pay.py:4", deps: [], command: null }] };
const QR = { uri: "otpauth://totp/FlowForge:key%20view?secret=JBSWY3DPEHPK3PXP&issuer=FlowForge", qr: "data:image/svg+xml;base64,PHN2Zy8+" };

function lockApi(start: "none" | "on" | "open", resetAt: string | null = null) {
  let state = start;
  const calls = mockApi({
    "/meta": META, "/issues": { repo: "trip", example: false, summary: {}, issues: [] }, "/keys": KEYS,
    "/lock": () => ({ state: state === "open" ? "on" : state, open: state === "open", seconds_left: state === "open" ? 300 : 0, reset_at: resetAt }),
    "/lock/setup": QR,
    "/lock/confirm": () => { state = "on"; return { state: "on" }; },
    "/lock/open": () => { state = "open"; return { open: true, seconds_left: 300 }; },
    "/lock/close": () => { state = "on"; return { open: false }; },
    "/keys/hidden": { items: [{ where: "code", name: "STRIPE_KEY", ref: "pay.py:4" }, { where: "saved", name: "RAZORPAY_KEY", ref: null }] },
    "/keys/reveal": { value: FAKE },
  });
  return calls;
}

const view = () => screen.findByRole("region", { name: "Key values" });

test("first time: a password, the QR, then the phone's code turns the lock on", async () => {
  const calls = lockApi("none");
  renderAt("/keys");
  await userEvent.click(within(await view()).getByRole("button", { name: /Set up/ }));
  await userEvent.type(screen.getByLabelText("Password"), "correct horse");
  await userEvent.type(screen.getByLabelText("Password again"), "correct horse");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByRole("img", { name: /QR code/ })).toHaveAttribute("src", QR.qr);
  await userEvent.type(screen.getByLabelText("Code from your phone"), "482917");
  await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
  const confirm = calls.find((c) => c.url === "/lock/confirm");
  expect(JSON.parse(String(confirm?.init?.body))).toEqual({ password: "correct horse", code: "482917" });
  expect(await screen.findByText("Open your key values")).toBeInTheDocument();   // straight to opening it
  expect(screen.getByLabelText("Password")).toHaveValue("");
});

test("passwords that differ are caught before anything is sent", async () => {
  const calls = lockApi("none");
  renderAt("/keys");
  await userEvent.click(within(await view()).getByRole("button", { name: /Set up/ }));
  await userEvent.type(screen.getByLabelText("Password"), "correct horse");
  await userEvent.type(screen.getByLabelText("Password again"), "correct horsf");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("differ");
  expect(calls.some((c) => c.url === "/lock/setup")).toBe(false);
});

test("open with the password and the code, then show one value at a time", async () => {
  const calls = lockApi("on");
  renderAt("/keys");
  await userEvent.click(within(await view()).getByRole("button", { name: /Open/ }));
  await userEvent.type(screen.getByLabelText("Password"), "correct horse");
  await userEvent.type(screen.getByLabelText("Code from your phone"), "482917");
  await userEvent.click(screen.getByRole("button", { name: "Unlock" }));
  expect(calls.find((c) => c.url === "/lock/open")?.init?.method).toBe("POST");
  expect(await screen.findByText(/locks in 5:00|locks in 4:5\d/)).toBeInTheDocument();
  expect(document.body.innerHTML).not.toContain(FAKE);                       // masked until Show
  const row = (await screen.findByText("STRIPE_KEY", { selector: ".kv-name" })).closest("li")!;
  await userEvent.click(within(row).getByRole("button", { name: "Show" }));
  expect(await within(row).findByText(FAKE)).toBeInTheDocument();
  await userEvent.click(within(row).getByRole("button", { name: /Hide/ }));
  expect(document.body.innerHTML).not.toContain(FAKE);
});

test("a shown value hides itself after 30 seconds", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  lockApi("open");
  renderAt("/keys");
  const row = (await screen.findByText("RAZORPAY_KEY", { selector: ".kv-name" })).closest("li")!;
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  await user.click(within(row).getByRole("button", { name: "Show" }));
  expect(await within(row).findByText(FAKE)).toBeInTheDocument();
  await act(async () => { vi.advanceTimersByTime(31_000); });
  expect(document.body.innerHTML).not.toContain(FAKE);
});

test("Lock now closes it, and a forced reset is shown until the next unlock", async () => {
  const calls = lockApi("open", "2026-10-24T14:02:00+00:00");
  renderAt("/keys");
  expect(await screen.findByRole("alert")).toHaveTextContent("Key view was reset");
  await userEvent.click(await screen.findByRole("button", { name: "Lock now" }));
  expect(calls.find((c) => c.url === "/lock/close")?.init?.method).toBe("POST");
  expect(await within(await view()).findByRole("button", { name: /Open/ })).toBeInTheDocument();
});
