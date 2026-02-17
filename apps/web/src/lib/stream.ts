import type { ChatStreamEvent } from "@/lib/types";

export function parseNdjsonChunk(chunk: string, carry = ""): { events: ChatStreamEvent[]; carry: string } {
  const input = `${carry}${chunk}`;
  const lines = input.split("\n");
  const nextCarry = lines.pop() ?? "";
  const events: ChatStreamEvent[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    events.push(JSON.parse(trimmed) as ChatStreamEvent);
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
    onEvent(JSON.parse(carry) as ChatStreamEvent);
  }
}
