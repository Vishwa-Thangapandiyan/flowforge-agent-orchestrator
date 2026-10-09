import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CATALOG } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

const TEST = {
  id: "stripe", name: "Stripe", mock: true, mode: "Demo only: example data, no network, no key needed.",
  steps: [{ title: "Connect in test mode", text: "a live key is refused" }, { title: "Create a test order", text: "POST /v1/orders" },
    { title: "Read it back", text: "GET /v1/orders/{id}" }],
  result: '{ "status": "created" }', stats: "0.3 s", learns: ["create order"],
};

test("the catalog splits what's on the map from what's only connected", async () => {
  mockApi({ "/meta": META, "/catalog": CATALOG });
  renderAt("/connectors");
  expect(await screen.findByRole("heading", { name: "Connect as many apps as you like" })).toBeInTheDocument();
  expect(within(screen.getByLabelText("On the map")).getByText("Google Gemini")).toBeInTheDocument();
  const idle = screen.getByLabelText("Connected, not in your code");
  expect(within(idle).getByText("Ollama")).toBeInTheDocument();
  expect(within(idle).getByText("Inventory API")).toBeInTheDocument();
  expect(screen.getAllByText("Live").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Demo only").length).toBeGreaterThan(0);
  expect(screen.getAllByRole("link", { name: "Add" })[0]).toHaveAttribute("href", "/connectors/new?preset=stripe");
});

test("search and Live only filter the cards", async () => {
  mockApi({ "/meta": META, "/catalog": CATALOG });
  renderAt("/connectors");
  await screen.findByText("Global payments.");
  await userEvent.type(screen.getByLabelText("Search apps"), "images");
  expect(screen.getByText("Images and video.")).toBeInTheDocument();
  expect(screen.queryByText("Global payments.")).not.toBeInTheDocument();
  await userEvent.clear(screen.getByLabelText("Search apps"));
  await userEvent.click(screen.getByRole("button", { name: "Live only" }));
  expect(screen.queryByText("Global payments.")).not.toBeInTheDocument();
  expect(screen.getByText("Quick model.")).toBeInTheDocument();
});

test("a mock test run shows what happens and what the Planner learns", async () => {
  const calls = mockApi({ "/meta": META, "/catalog": CATALOG, "/catalog/stripe/test": TEST });
  renderAt("/connectors");
  const card = (await screen.findByText("Global payments.")).closest("article") as HTMLElement;
  await userEvent.click(within(card).getByRole("button", { name: /Test run/ }));
  const drawer = await screen.findByRole("dialog", { name: "Test run: Stripe" });
  expect(within(drawer).getByText(/no network, no key needed/)).toBeInTheDocument();
  expect(await within(drawer).findByText("create order", {}, { timeout: 3000 })).toBeInTheDocument();
  expect(calls.find((c) => c.url === "/catalog/stripe/test")?.init?.method).toBe("POST");
});
