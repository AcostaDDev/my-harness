import assert from "node:assert/strict";
import test from "node:test";
import { estimateMinutes } from "../.build/estimate.js";

test("calculates zero, one and several tasks", () => {
  assert.equal(estimateMinutes(0), 0);
  assert.equal(estimateMinutes(1), 30);
  assert.equal(estimateMinutes(3), 90);
});

test("rejects negative, fractional and invalid inputs", () => {
  for (const value of [-1, 1.5, NaN, Infinity]) {
    assert.throws(() => estimateMinutes(value), RangeError);
  }
});
