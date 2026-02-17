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
});
