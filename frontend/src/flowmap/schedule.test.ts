import { expect, test } from "vitest";
import { CODEFLOW } from "../test/flowFixture";
import { scheduleTrace } from "./schedule";

test("Watch it run plays the could-be schedule: each call as early as its inputs allow, for its weight", () => {
  const trace = scheduleTrace(CODEFLOW);
  const at = Object.fromEntries(trace.steps.map((s) => [s.node, [s.start_ms, s.duration_ms]]));
  expect(at["api-nominatim-1"]).toEqual([0, 420]);
  expect(at["mcp-fetch-1"]).toEqual([420, 6800]);          // waits for the city check, nothing else
  expect(at["api-open-meteo-1"]).toEqual([420, 180]);      // starts with fetch
  expect(at["llm-ollama-1"]).toEqual([7220, 2000]);        // waits for the slowest input
  expect(at["stop-1"]).toBeUndefined();                    // the early stop isn't taken
  expect(trace.branches).toEqual({ "if-1": "no" });        // decisions carry on to the work
  expect(trace.label).toBe("the could-be schedule, not a recording");
});
