import { expect, test } from "vitest";
import { EDGES, NODES } from "../test/flowFixture";
import { autoLayout, placeAll } from "./layout";

test("auto-layout runs left to right along the lines", () => {
  const pos = autoLayout(NODES, EDGES);
  expect(pos.start[0]).toBeLessThan(pos.fetch[0]);
  expect(pos.fetch[0]).toBeLessThan(pos.risky[0]);
  expect(pos.gate_send[0]).toBeLessThan(pos.send[0]);
  expect(pos.send[0]).toBeLessThan(pos.end[0]);
});

test("saved positions win; only new blocks are auto-placed", () => {
  const saved = Object.fromEntries(NODES.filter((n) => n.id !== "sms").map((n, i) => [n.id, [i * 10, 5] as [number, number]]));
  const pos = placeAll(NODES, EDGES, saved);
  expect(pos.fetch).toEqual(saved.fetch);
  expect(pos.sms).not.toEqual([0, 0]);
});
