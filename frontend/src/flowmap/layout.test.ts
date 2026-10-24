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

describe("lanes on a dependency map (D38)", async () => {
  const { kindLanes, boxes, busPaths, LANE_ORDER } = await import("./themes");
  const { DEPS } = await import("../test/flowFixture");
  const placed = kindLanes(DEPS);
  const nodes = DEPS.nodes.map((n) => ({ id: n.id, position: { x: placed[n.id][0], y: placed[n.id][1] }, width: 196, height: 64, data: {} }));
  const rects = boxes(DEPS, nodes);

  it("never lets two boxes overlap", () => {
    for (const a of rects) for (const b of rects) {
      if (a === b) continue;
      const apart = a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
      expect(apart, `${a.label} overlaps ${b.label}`).toBe(true);
    }
  });

  it("puts every block in its own kind's lane, lanes in order, start blocks on the left", () => {
    const xs = LANE_ORDER.map((k) => DEPS.nodes.filter((n) => n.kind === k).map((n) => placed[n.id][0]))
      .filter((l) => l.length);
    for (const lane of xs) expect(new Set(lane).size).toBe(1);
    expect(xs.map((l) => l[0])).toEqual([...xs.map((l) => l[0])].sort((a, b) => a - b));
    for (const n of DEPS.nodes.filter((n) => n.kind === "start")) expect(placed[n.id][0]).toBeLessThan(Math.min(...xs.map((l) => l[0])));
  });

  it("draws one bus line per lane from each start block, above the lanes", () => {
    const paths = busPaths(DEPS, nodes, rects);
    expect(paths.length).toBeGreaterThan(0);
    const top = Math.min(...rects.map((r) => r.y));
    for (const p of paths) {
      const ys = [...p.d.matchAll(/L\d+(?:\.\d+)? (-?\d+(?:\.\d+)?)/g)].map((m) => Number(m[1]));
      expect(ys[0]).toBeLessThan(top);   // the run along the top
    }
  });
});
