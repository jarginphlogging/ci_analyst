import assert from "node:assert/strict";
import test from "node:test";
import { detectRoute, evaluateNumericAssertions, percentile, scoreTokenMatch } from "./score.mjs";

test("scoreMatch passes when any expected token is present", () => {
  const result = scoreTokenMatch("Fraud loss rate rose 28 bps.", ["deposit", "fraud"]);
  assert.equal(result.pass, true);
  assert.equal(result.hitCount, 1);
});

test("scoreMatch fails when expected tokens are absent", () => {
  const result = scoreTokenMatch("Charge-off increased.", ["liquidity", "nim"]);
  assert.equal(result.pass, false);
  assert.equal(result.hitCount, 0);
});

test("detectRoute returns deep_path from assumptions", () => {
  const payload = {
    response: {
      assumptions: ["Deep path was selected for multi-step reasoning."],
    },
  };
  assert.equal(detectRoute(payload), "deep_path");
});

test("evaluateNumericAssertions validates metric value and unit", () => {
  const payload = {
    response: {
      metrics: [{ label: "Total Spend", value: 2.83, delta: 0.27, unit: "usd" }],
    },
  };
  const result = evaluateNumericAssertions(payload, [
    { label: "Total Spend", field: "value", expected: 2.83, tolerance: 0.001, unit: "usd" },
  ]);
  assert.equal(result.pass, true);
  assert.equal(result.checks[0].pass, true);
});

test("percentile returns nearest-rank p95", () => {
  const p95 = percentile([100, 150, 250, 900], 95);
  assert.equal(p95, 900);
});
