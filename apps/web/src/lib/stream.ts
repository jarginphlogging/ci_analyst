import { chatStreamEventSchema } from "@ci/contracts";
import type { ChatStreamEvent } from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasString(value: Record<string, unknown>, key: string): boolean {
  return typeof value[key] === "string";
}

function isFallbackEvent(payload: unknown): payload is ChatStreamEvent {
  if (!isRecord(payload)) return false;
  const type = payload.type;
  if (type === "status") return hasString(payload, "message");
  if (type === "answer_delta") return hasString(payload, "delta");
  if (type === "error") return hasString(payload, "message");
  if (type === "done") return true;
  if (type !== "response") return false;
  if (!isRecord(payload.response)) return false;
  return typeof payload.response.answer === "string";
}

function validateStreamEvent(payload: unknown): ChatStreamEvent {
  const parsed = chatStreamEventSchema.safeParse(payload);
  if (!parsed.success) {
    if (isFallbackEvent(payload)) {
      return payload;
    }
    throw new Error("Invalid stream event payload");
  }
  return payload as ChatStreamEvent;
}

export function parseNdjsonChunk(chunk: string, carry = ""): { events: ChatStreamEvent[]; carry: string } {
  const input = `${carry}${chunk}`;
  const lines = input.split("\n");
  const nextCarry = lines.pop() ?? "";
  const events: ChatStreamEvent[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    events.push(validateStreamEvent(JSON.parse(trimmed) as unknown));
  }

  return { events, carry: nextCarry };
}

export async function readNdjsonStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let carry = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const decoded = decoder.decode(value, { stream: true });
    const parsed = parseNdjsonChunk(decoded, carry);
    carry = parsed.carry;
    for (const event of parsed.events) {
      onEvent(event);
    }
  }

  if (carry.trim()) {
    onEvent(validateStreamEvent(JSON.parse(carry) as unknown));
  }
}
