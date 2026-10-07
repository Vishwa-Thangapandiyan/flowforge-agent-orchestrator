import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS, connector } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

const FAKE = "sk_test_FAKEFAKE12345678";
const type = (label: RegExp | string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

test("switching type changes the fields, and the saved JSON follows as you type", async () => {
  mockApi({ "/meta": META, "/connectors": CONNECTORS, "/presets": [] });
  renderAt("/connectors/new");
  await screen.findByRole("heading", { name: "Connect it, colour it, name it" });
  fireEvent.click(screen.getByRole("button", { name: /^LLM/ }));
  expect(screen.getByLabelText("Model")).toBeInTheDocument();
  type("Name", "Image studio");
  type("Model", "studio-1");
  type("Base URL", "https://img.test/v1");
  type(/Key: the name of the variable/, "IMAGE_STUDIO_KEY");
  const saved = screen.getByLabelText("What gets saved");
  expect(saved).toHaveTextContent('"id": "image-studio"');
  expect(saved).toHaveTextContent('"secret_ref": "env:IMAGE_STUDIO_KEY"');
  fireEvent.click(screen.getByRole("button", { name: /^Local command/ }));
  expect(screen.getByLabelText(/Run in folder/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Model")).not.toBeInTheDocument();
});

test("a pasted key is refused and never shown or sent", async () => {
  const calls = mockApi({ "/meta": META, "/connectors": CONNECTORS, "/presets": [] });
  renderAt("/connectors/new");
  fireEvent.click(await screen.findByRole("button", { name: /^HTTP API/ }));
  type("Name", "Stripe");
  type(/Base URL/, "https://api.stripe.com/v1");
  type(/Key: the name of the variable/, FAKE);
  expect(screen.getByText(/looks like a key itself/)).toBeInTheDocument();
  expect(screen.getByLabelText("What gets saved")).not.toHaveTextContent("FAKEFAKE");
  fireEvent.click(screen.getByRole("button", { name: /Add to project/ }));
  await vi.waitFor(() => expect(screen.getByText(/need another look/)).toBeInTheDocument());
  expect(calls.some((c) => c.init?.method === "POST" && c.url === "/connectors")).toBe(false);
});

test("adding posts the connector and opens its page", async () => {
  const calls = mockApi({
    "/meta": META, "/connectors": (init?: RequestInit) => (init?.method === "POST" ? connector({ id: "scan", type: "local", name: "Scan" }) : CONNECTORS),
    "/presets": [], "/connectors/scan": connector({ id: "scan", type: "local", name: "Scan" }), "/health/tools": [], "/connectors/scan/activity": [],
  });
  renderAt("/connectors/new");
  fireEvent.click(await screen.findByRole("button", { name: /^Local command/ }));
  type("Name", "Scan");
  type(/^Command/, "./scan.sh --quick");
  type(/Run in folder/, "tools");
  fireEvent.click(screen.getByRole("radio", { name: "Colour #2F6FD6" }));
  fireEvent.click(screen.getByRole("button", { name: /Add to project/ }));
  await vi.waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true));
  const body = JSON.parse(String(calls.find((c) => c.init?.method === "POST")!.init!.body));
  expect(body).toMatchObject({ id: "scan", type: "local", connection: { command: ["./scan.sh", "--quick"], cwd: "tools" },
    style: { color: "#2F6FD6" } });
  expect(await screen.findByRole("heading", { name: "Scan", level: 1 })).toBeInTheDocument();
});

test("a ready-made app fills the form", async () => {
  mockApi({ "/meta": META, "/connectors": CONNECTORS, "/presets": [
    { preset: "stripe", id: "stripe", type: "http", name: "Stripe", role: "payments", mode: "test", slot: "payments",
      secret_ref: "env:STRIPE_SECRET_KEY", style: { color: "#635BFF", logo: { type: "letters", text: "St" } },
      connection: { base_url: "https://api.stripe.com/v1", auth_header: "Authorization", auth_scheme: "bearer" } }] });
  renderAt("/connectors/new");
  const presets = await screen.findByRole("region", { name: "Start from a ready-made app" });
  fireEvent.click(within(presets).getByRole("button", { name: /Stripe/ }));
  expect(screen.getByLabelText("Name")).toHaveValue("Stripe");
  expect(screen.getByLabelText(/Key: the name of the variable/)).toHaveValue("STRIPE_SECRET_KEY");
  expect(screen.getByLabelText("What gets saved")).toHaveTextContent('"mode": "test"');
});
