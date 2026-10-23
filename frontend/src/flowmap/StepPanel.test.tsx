import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { Connector } from "../api/types";
import { CONNECTORS } from "../test/fixtures";
import { mockApi } from "../test/api";
import { CHECKS, CODEFLOW, DEPS, FLOW } from "../test/flowFixture";
import { StepPanel, type PanelActions } from "./StepPanel";

function actions(): PanelActions {
  return { close: vi.fn(), approve: vi.fn(), reject: vi.fn(), edit: vi.fn(async () => {}), reset: vi.fn(async () => {}), dismissTip: vi.fn() };
}
const node = (id: string) => FLOW.nodes.find((n) => n.id === id)!;
const LLMS: Connector[] = CONNECTORS.filter((c) => c.type === "llm"); // Gemini and NVIDIA NIM

function show(id: string, extra: Partial<Parameters<typeof StepPanel>[0]> = {}) {
  const a = actions();
  render(<StepPanel node={node(id)} flow={FLOW} tile={null} state="idle" cap="" waiting={false} connectors={LLMS}
    tipShown layer="mine" actions={a} {...extra} />);
  return a;
}

test("an LLM step shows its evidence with the cited line, its runs and the Planner's tip", async () => {
  const a = show("score");
  expect(screen.getByRole("heading", { name: "Score fraud risk" })).toBeInTheDocument();
  expect(screen.getByText("app/score.py:11")).toBeInTheDocument();
  expect(document.querySelector(".sp-cl.hl")).toHaveTextContent("call()");
  expect(screen.getByText("p50 2.1 s · 2 rate-limited in 40")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^Use / }));
  expect(a.edit).toHaveBeenCalledWith({ op: "set_connector", node: "score", connector: "nim" });
});

test("swapping the app is an edit, never a code change", async () => {
  const a = show("score");
  await userEvent.selectOptions(screen.getByLabelText("Use another app for this step"), "nim");
  expect(a.edit).toHaveBeenCalledWith({ op: "set_connector", node: "score", connector: "nim" });
  expect(screen.getByText(/never your code/)).toBeInTheDocument();
});

test("a gate can't be removed, and offers Approve while a run waits on it", async () => {
  const a = show("gate_send", { waiting: true, state: "waiting" });
  expect(screen.getByText(/Always gated/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Gates can't be removed" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(a.approve).toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent("Waiting for you to approve");
});

test("an unconfirmed step says why and can be confirmed or hidden", async () => {
  const a = show("sms");
  expect(screen.getByText(/It never runs until you confirm it/)).toBeInTheDocument();
  expect(screen.getByText(".env.example:7")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Keep as my step" }));
  expect(a.edit).toHaveBeenCalledWith({ op: "confirm", node: "sms" });
});

test("a decision lists its branches; renaming saves an edit", async () => {
  const a = show("risky");
  const sec = screen.getByText("Condition, from the code").closest(".sp-sec") as HTMLElement;
  expect(within(sec).getByText("order.amount > 5000")).toBeInTheDocument();
  expect(within(sec).getByText("Score fraud risk")).toBeInTheDocument();
  const name = screen.getByLabelText("Name");
  await userEvent.clear(name);
  await userEvent.type(name, "Big order?");
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  expect(a.edit).toHaveBeenCalledWith({ op: "rename", node: "risky", title: "Big order?" });
});

test("the Planner's map is read-only", () => {
  show("score", { layer: "planner" });
  expect(screen.queryByText("Edit")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Use another app for this step")).not.toBeInTheDocument();
});

test("a scanned dependency shows the address it will be checked at, not an app to connect", async () => {
  const dep = (id: string) => DEPS.nodes.find((n) => n.id === id)!;
  const { rerender } = render(<StepPanel node={dep("api-nominatim")} flow={DEPS} tile={null} state="idle" cap="" waiting={false}
    connectors={[]} tipShown layer="mine" actions={actions()} />);
  expect(screen.getByText("https://nominatim.openstreetmap.org/search")).toBeInTheDocument();   // under its name
  expect(screen.queryByText("What it does")).not.toBeInTheDocument();
  expect(screen.queryByText(/not connected/)).not.toBeInTheDocument();   // nothing to connect: it's not an error
  rerender(<StepPanel node={dep("mcp-fetch")} flow={DEPS} tile={null} state="idle" cap="" waiting={false}
    connectors={[]} tipShown layer="mine" actions={actions()} />);
  expect(screen.getByText(DEPS.nodes.find((n) => n.id === "mcp-fetch")!.what)).toBeInTheDocument();   // the command it starts with
  rerender(<StepPanel node={dep("api-www-mysite-test")} flow={DEPS} tile={null} state="idle" cap="" waiting={false}
    connectors={[]} tipShown layer="mine" actions={actions()} />);
  expect(screen.getByText(/only mentions it/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Keep it" })).toBeInTheDocument();
});

test("a dependency's Health says why it is down and how to fix it, and can be checked alone", async () => {
  mockApi({ "/checks/llm-ollama": [
    { run_id: "chk1", status: "down", latency_ms: null, summary: "Nothing answers at localhost:11434",
      reason: "[Errno 111] Connection refused", fix: "Start Ollama (`ollama serve`).", at: "2026-10-21T10:44:00Z" },
    { run_id: "chk0", status: "up", latency_ms: 300, summary: "Up", reason: null, fix: null, at: "2026-10-21T09:10:00Z" }] });
  const onCheck = vi.fn();
  const ollama = DEPS.nodes.find((n) => n.id === "llm-ollama")!;
  render(<StepPanel node={ollama} flow={DEPS} tile={null} state="idle" cap="" waiting={false} connectors={[]} tipShown
    layer="mine" actions={actions()} health={CHECKS.items[0]} othersUp={3} onCheck={onCheck} />);
  expect(screen.getByText("Down: Nothing answers at localhost:11434")).toBeInTheDocument();
  // it isn't your connection: other dependencies answered in the same check
  expect(screen.getByText("Your internet works: 3 others answered when last checked.")).toBeInTheDocument();
  expect(screen.getByText("[Errno 111] Connection refused")).toBeInTheDocument();
  expect(screen.getByText("Start Ollama (`ollama serve`).")).toBeInTheDocument();
  expect(await screen.findByRole("img", { name: "last 2 checks" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Check this one/ }));
  expect(onCheck).toHaveBeenCalledWith("llm-ollama");
  vi.unstubAllGlobals();
});

test("a step read from code says how long it takes and where that number came from", () => {
  const fetch = { ...CODEFLOW.nodes.find((n) => n.id === "mcp-fetch-1")!, repeats: true };
  render(<StepPanel node={fetch} flow={CODEFLOW} tile={null} state="idle" cap="" waiting={false} connectors={[]} tipShown
    layer="mine" actions={actions()} />);
  expect(screen.getByText("6.8 s · measured")).toBeInTheDocument();
  expect(screen.getByText("Repeats in a loop")).toBeInTheDocument();
  expect(screen.queryByText(/not connected/)).not.toBeInTheDocument();   // a code flow needs no connected app (D25)
});
