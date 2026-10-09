import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { Connector } from "../api/types";
import { CONNECTORS } from "../test/fixtures";
import { FLOW } from "../test/flowFixture";
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
  expect(screen.getByText("On the critical path")).toBeInTheDocument();
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
