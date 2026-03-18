import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseNdjsonChunk } from "./stream";

describe("parseNdjsonChunk", () => {
  it("parses complete lines and returns carry", () => {
    const first = parseNdjsonChunk('{"type":"status","message":"A"}\n{"type":"done"}\n');
    assert.equal(first.events.length, 2);
    assert.equal(first.carry, "");
  });

  it("handles partial chunks", () => {
    const first = parseNdjsonChunk('{"type":"status","message":"A"}\n{"type":"answer_delta"');
    assert.equal(first.events.length, 1);
    const second = parseNdjsonChunk(',"delta":"x"}\n', first.carry);
    assert.equal(second.events.length, 1);
    assert.deepEqual(second.events[0], { type: "answer_delta", delta: "x" });
  });

  it("accepts response events with nullable trace fields", () => {
    const line =
      '{"type":"response","response":{"summary":{"answer":"Blocked","confidence":"low","whyItMatters":"Need clarification","summaryCards":[],"insights":[],"suggestedQuestions":[],"assumptions":[]},"visualization":{},"data":{"dataTables":[],"evidence":[]},"audit":{},"trace":[{"id":"t2","title":"Generate and execute SQL","summary":"blocked","status":"blocked","sql":null,"qualityChecks":null}]}}\n';
    const parsed = parseNdjsonChunk(line);
    assert.equal(parsed.events.length, 1);
    assert.equal(parsed.events[0].type, "response");
  });

  it("falls back to tolerant parsing when response shape drifts", () => {
    const line = '{"type":"response","response":{"summary":{"answer":"Fallback answer"}}}\n';
    const parsed = parseNdjsonChunk(line);
    assert.equal(parsed.events.length, 1);
    assert.deepEqual(parsed.events[0], {
      type: "response",
      response: { summary: { answer: "Fallback answer" } },
    });
  });
});
