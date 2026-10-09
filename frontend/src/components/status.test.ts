import { expect, test } from "vitest";
import { healthTone, runTone, stepTone } from "./status";

test("colour meanings are fixed", () => {
  expect(runTone("succeeded")[0]).toBe("teal");
  expect(runTone("running")[0]).toBe("blue");
  expect(runTone("failed")[0]).toBe("coral");
  expect(runTone("waiting")[0]).toBe("amber");
  expect(stepTone("running")[0]).toBe("blue");
  expect(stepTone("succeeded")).toEqual(["teal", "done"]);
  expect(healthTone("missing_key")).toBe("amber");
  expect(healthTone("failing")).toBe("coral");
});
