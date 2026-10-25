import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { CONNECTORS } from "../test/fixtures";
import { CHECKS, DEPS, PLAN } from "../test/flowFixture";

afterEach(() => vi.unstubAllGlobals());

const REAL = { ...META, example: false };

test("the map shows each dependency's health on its block, with no extra strip (D33)", async () => {
  mockApi({ "/meta": REAL, "/flow": DEPS, "/connectors": CONNECTORS, "/checks": CHECKS, "/checks/plan": PLAN });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  await vi.waitFor(() => expect(document.querySelector(".ff-block.h-down")).toHaveTextContent("Ollama"));
  expect(screen.queryByRole("img", { name: /up, .* down/ })).not.toBeInTheDocument();
  expect(document.querySelector(".ff-block.h-warn")).toHaveTextContent("fetch");
  expect(screen.getByText("420 ms", { exact: false })).toBeInTheDocument();
});

test("each block's result sits inside that block, never under it where the next block starts", async () => {
  // Vishwa read Overpass's "no answer within 10 s", drawn under Overpass, as Supabase's (the block below it)
  mockApi({ "/meta": REAL, "/flow": DEPS, "/connectors": CONNECTORS, "/checks": CHECKS, "/checks/plan": PLAN });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  await vi.waitFor(() => expect(document.querySelector(".ff-block.h-down")).toBeTruthy());
  const block = (title: string) => screen.getByText(title, { selector: ".ff-title" }).closest(".ff-block")!;
  expect(block("Nominatim").querySelector(".ff-sub")).toHaveTextContent("420 ms");
  expect(block("Ollama").querySelector(".ff-sub .ff-h.down")).toBeTruthy();
  expect(document.querySelectorAll(".ff-cap .ff-h")).toHaveLength(0);   // nothing hangs below a block
});

test("a block with a missing key keeps what it is next to the notice", async () => {
  const { render } = await import("@testing-library/react");
  const { ReactFlowProvider } = await import("@xyflow/react");
  const { CardNode } = await import("../flowmap/nodes");
  const node = DEPS.nodes.find((n) => n.id === "api-nominatim")!;
  const data = { node, tile: null, deps: true, code: false, state: "idle", cap: "", cp: false, search: null, keyNeed: "missing" };
  const props = { id: node.id, data, selected: false } as unknown as Parameters<typeof CardNode>[0];
  render(<ReactFlowProvider><CardNode {...props} /></ReactFlowProvider>);
  const sub = document.querySelector(".ff-sub")!;
  expect(sub).toHaveTextContent("key missing · click to add");
  expect(sub).toHaveTextContent("nominatim.openstreetmap.org");
});

test("the first Check now lists what will start and waits for a yes", async () => {
  const posted: unknown[] = [];
  mockApi({
    "/meta": REAL, "/flow": DEPS, "/connectors": CONNECTORS, "/checks/plan": PLAN,
    "/checks": (init?: RequestInit) => {
      if (init?.method === "POST") { posted.push(JSON.parse(String(init.body))); return { run_id: "r9", checks: 5 }; }
      return { ...CHECKS, run_id: null };
    },
  });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  await userEvent.click(await screen.findByRole("button", { name: /Check now/ }));
  const panel = await screen.findByRole("region", { name: "Before checking" });
  expect(within(panel).getByText("Checking starts 2 MCP servers on this computer")).toBeInTheDocument();
  expect(within(panel).getByText("uvx mcp-server-fetch")).toBeInTheDocument();
  expect(within(panel).getByText("downloads from PyPI, any version")).toBeInTheDocument();
  expect(posted).toEqual([]);   // nothing starts before the yes
  await userEvent.click(within(panel).getByRole("button", { name: "Start them and check" }));
  await vi.waitFor(() => expect(posted).toEqual([{ confirm: true }]));
});

test("Check without them leaves the MCP servers out", async () => {
  const posted: unknown[] = [];
  mockApi({
    "/meta": REAL, "/flow": DEPS, "/connectors": CONNECTORS, "/checks/plan": PLAN,
    "/checks": (init?: RequestInit) => {
      if (init?.method === "POST") { posted.push(JSON.parse(String(init.body))); return { run_id: "r9", checks: 2 }; }
      return CHECKS;
    },
  });
  renderAt("/");
  await screen.findByText("Nominatim", { selector: ".ff-title" });
  await userEvent.click(await screen.findByRole("button", { name: /Check now/ }));
  await userEvent.click(await screen.findByRole("button", { name: "Check without them" }));
  await vi.waitFor(() => expect(posted).toEqual([{ ids: ["llm-ollama", "api-nominatim", "api-wikipedia"] }]));
});

test("the Checks page puts problems first, filters them, and shows one dependency's history", async () => {
  mockApi({
    "/meta": REAL, "/flow": DEPS, "/connectors": CONNECTORS, "/checks": CHECKS, "/checks/plan": PLAN,
    "/checks/llm-ollama": [
      { run_id: "chk1", status: "down", latency_ms: null, summary: "Nothing answers at localhost:11434",
        reason: "[Errno 111] Connection refused", fix: "Start Ollama (`ollama serve`).", at: "2026-10-21T10:44:00Z" },
      { run_id: "chk0", status: "up", latency_ms: 300, summary: "Up, llama3.1:8b is ready", reason: null, fix: null,
        at: "2026-10-21T09:10:00Z" }],
  });
  renderAt("/checks");
  expect(await screen.findByRole("heading", { name: "Checks", level: 1 })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Checks" })).toHaveAttribute("aria-current", "page");
  const rows = (await screen.findAllByRole("row")).slice(1);
  expect(rows).toHaveLength(6);
  expect(within(rows[0]).getByRole("rowheader")).toHaveTextContent("Ollama");   // down first
  expect(within(rows[1]).getByRole("rowheader")).toHaveTextContent("fetch");    // then needs a look
  await userEvent.click(screen.getByRole("button", { name: /Problems 2/ }));
  expect(screen.getAllByRole("row").slice(1)).toHaveLength(2);
  await userEvent.click(within(rows[0]).getByRole("button", { name: /Ollama/ }));
  const side = await screen.findByRole("region", { name: "Ollama history" });
  expect(within(side).getByText("Up, llama3.1:8b is ready")).toBeInTheDocument();
  expect(within(side).getByText("Start Ollama (`ollama serve`).")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Workflow runs (advanced)" })).toHaveAttribute("href", "/p/test/runs");
});

test("a block's caption shows its latency once, then what needs a look", async () => {
  const { caption } = await import("./Health");
  expect(caption("warn", "Up: 1 tool, but slow to start: 6.8 s", 6800)).toBe("6.8 s · slow to start");
  expect(caption("warn", "Up, but plain http://: not encrypted", 210)).toBe("210 ms · plain http://: not encrypted");
  expect(caption("up", "Up, needs a key (403)", 230)).toBe("230 ms · needs a key");
  expect(caption("down", "Stopped while starting", null)).toBe("stopped while starting");
  expect(caption("unconfirmed", "Not checked: unconfirmed", null)).toBe("");
});
