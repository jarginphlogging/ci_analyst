import assert from "node:assert/strict";
import test from "node:test";

function normalize(text) {
  return String(text || "").toLowerCase();
}

function scoreMatch(answer, expectedTokens) {
  const normalized = normalize(answer);
  const hits = expectedTokens.filter((token) => normalized.includes(normalize(token)));
  return {
    hitCount: hits.length,
    pass: hits.length > 0,
  };
}

test("scoreMatch passes when any expected token is present", () => {
  const result = scoreMatch("Fraud loss rate rose 28 bps.", ["deposit", "fraud"]);
  assert.equal(result.pass, true);
  assert.equal(result.hitCount, 1);
});

test("scoreMatch fails when expected tokens are absent", () => {
  const result = scoreMatch("Charge-off increased.", ["liquidity", "nim"]);
  assert.equal(result.pass, false);
  assert.equal(result.hitCount, 0);
});
