import { expect, test } from "vitest";
import { EMPTY, fromConnector, looksLikeKey, problems, slug, splitArgs, toConnector, type Form } from "./connectorForm";

const FAKE = "sk_test_FAKEFAKE12345678";

test("a pasted key is refused everywhere and never saved", () => {
  const f: Form = { ...EMPTY, type: "http", name: "Stripe", baseUrl: "https://api.stripe.com/v1", keyVar: FAKE, role: FAKE };
  const p = problems(f);
  expect(p.keyVar).toMatch(/looks like a key itself/);
  expect(p.role).toMatch(/looks like a key/);
  const saved = JSON.stringify(toConnector(f));
  expect(saved).not.toContain("FAKEFAKE");
  expect(saved).not.toContain("secret_ref");
});

test("an upper-cased key is still a key", () => {
  const f: Form = { ...EMPTY, type: "llm", name: "G", baseUrl: "https://g.test", model: "m", keyVar: FAKE.toUpperCase() };
  expect(problems(f).keyVar).toMatch(/looks like a key itself/);
  expect(JSON.stringify(toConnector(f))).not.toMatch(/FAKEFAKE/i);
});

test("the key is saved as a reference to an environment variable", () => {
  const f: Form = { ...EMPTY, type: "llm", name: "My Gemini", baseUrl: "https://g.test/v1", model: "m", keyVar: "GEMINI_API_KEY", rpm: "15" };
  expect(problems(f)).toEqual({});
  expect(toConnector(f)).toEqual({
    id: "my-gemini", type: "llm", name: "My Gemini", role: "", rate_limit_rpm: 15, secret_ref: "env:GEMINI_API_KEY",
    style: { color: EMPTY.color, logo: { type: "letters", text: "MG" } },
    connection: { provider: "openai_compatible", model: "m", base_url: "https://g.test/v1" },
  });
});

test("each type saves its own connection shape", () => {
  expect(toConnector({ ...EMPTY, type: "mcp", name: "Image studio", command: "npx", args: 'my-image-mcp --dir "C:/My Images"' }).connection)
    .toEqual({ command: "npx", args: ["my-image-mcp", "--dir", "C:/My Images"] });
  expect(toConnector({ ...EMPTY, type: "local", name: "Scan", command: "./scan.sh --quick", cwd: "project/tools" }).connection)
    .toEqual({ command: ["./scan.sh", "--quick"], cwd: "project/tools" });
  expect(toConnector({ ...EMPTY, type: "http", name: "Pay", baseUrl: "https://api.x", keyVar: "PAY_KEY", authScheme: "basic" }))
    .toMatchObject({ secret_ref: "env:PAY_KEY", connection: { base_url: "https://api.x", auth_header: "Authorization", auth_scheme: "basic" } });
});

test("validation in plain words", () => {
  expect(problems({ ...EMPTY, type: "local" })).toMatchObject({ name: "Give it a name.", command: expect.any(String), cwd: expect.any(String) });
  expect(problems({ ...EMPTY, name: "x", id: "llm" }).id).toMatch(/reserved/);
  expect(problems({ ...EMPTY, name: "x", command: "uvx", keyVar: "my key" }).keyVar).toMatch(/capital letters/);
});

test("editing round-trips a saved connector", () => {
  const saved = toConnector({ ...EMPTY, type: "http", name: "Razorpay", role: "payments", baseUrl: "https://api.razorpay.com/v1",
    keyVar: "RAZORPAY_KEY", authScheme: "basic", mode: "test", slot: "payments", rpm: "60", color: "#3395FF", letters: "Rz" });
  expect(toConnector(fromConnector(saved as never))).toEqual(saved);
});

test("helpers", () => {
  expect(slug("Image studio!")).toBe("image-studio");
  expect(slug("2fast")).toBe("app-2fast");
  expect(splitArgs("a 'b c' \"d\"")).toEqual(["a", "b c", "d"]);
  expect(looksLikeKey("rzp_test_FAKE1234567")).toBe(true);
  expect(looksLikeKey("GEMINI_API_KEY")).toBe(false);
});
