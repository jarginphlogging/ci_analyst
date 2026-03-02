import { describe, expect, it } from "vitest";
import { parseNdjsonChunk } from "./stream";

describe("parseNdjsonChunk", () => {
  it("parses complete lines and returns carry", () => {
    const first = parseNdjsonChunk('{"type":"status","message":"A"}\n{"type":"done"}\n');
    expect(first.events).toHaveLength(2);
    expect(first.carry).toBe("");
  });

  it("handles partial chunks", () => {
    const first = parseNdjsonChunk('{"type":"status","message":"A"}\n{"type":"answer_delta"');
    expect(first.events).toHaveLength(1);
    const second = parseNdjsonChunk(',"delta":"x"}\n', first.carry);
    expect(second.events).toHaveLength(1);
    expect(second.events[0]).toEqual({ type: "answer_delta", delta: "x" });
  });

  it("accepts response events with nullable trace fields", () => {
    const line =
      '{"type":"response","phase":"final","response":{"answer":"Blocked","confidence":"low","whyItMatters":"Need clarification","metrics":[],"evidence":[],"insights":[],"suggestedQuestions":[],"assumptions":[],"trace":[{"id":"t2","title":"Generate and execute SQL","summary":"blocked","status":"blocked","sql":null,"qualityChecks":null}],"dataTables":[]}}\n';
    const parsed = parseNdjsonChunk(line);
    expect(parsed.events).toHaveLength(1);
    expect(parsed.events[0].type).toBe("response");
  });

  it("falls back to tolerant parsing when response shape drifts", () => {
    const line = '{"type":"response","phase":"final","response":{"answer":"Fallback answer"}}\n';
    const parsed = parseNdjsonChunk(line);
    expect(parsed.events).toHaveLength(1);
    expect(parsed.events[0]).toEqual({
      type: "response",
      phase: "final",
      response: { answer: "Fallback answer" },
    });
  });
});
