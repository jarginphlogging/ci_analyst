import type { ChatStreamEvent } from "@/lib/types";
import { getMockAgentResponse } from "@/lib/mock-agent";

interface StreamDelays {
  statusMs: number;
  tokenMs: number;
  responseMs: number;
}

export function buildMockEvents(message: string): ChatStreamEvent[] {
  const response = getMockAgentResponse(message);
  const draftAnswer = response.answer.split(".")[0]?.trim();
  const draftResponse = draftAnswer
    ? { ...response, answer: `${draftAnswer}.` }
    : response;
  const events: ChatStreamEvent[] = [
    { type: "status", message: "Understanding your question" },
    { type: "status", message: "Planning analysis..." },
    { type: "status", message: "Resolving latest RESP_DATE context from semantic model" },
    { type: "status", message: "Preparing data retrieval and running checks" },
    { type: "status", message: "Retrieving data and preparing evidence tables" },
    { type: "status", message: "Running numeric QA and consistency checks" },
    { type: "status", message: "Ranking insights by impact and confidence" },
    { type: "response", phase: "draft", response: draftResponse },
  ];

  for (const token of response.answer.split(" ")) {
    events.push({ type: "answer_delta", delta: `${token} ` });
  }

  events.push({ type: "status", message: "Finalizing response payload and audit trace" });
  events.push({ type: "response", phase: "final", response });
  events.push({ type: "done" });

  return events;
}

function delayForEvent(event: ChatStreamEvent, delays: StreamDelays): number {
  if (event.type === "status") return Math.max(0, delays.statusMs);
  if (event.type === "answer_delta") return Math.max(0, delays.tokenMs);
  if (event.type === "response") return Math.max(0, delays.responseMs);
  return 0;
}

export async function streamMockEvents(
  events: ChatStreamEvent[],
  write: (chunk: string) => void,
  delays: StreamDelays = { statusMs: 650, tokenMs: 110, responseMs: 400 },
  signal?: AbortSignal,
): Promise<void> {
  for (const event of events) {
    if (signal?.aborted) return;
    write(`${JSON.stringify(event)}\n`);
    const eventDelay = delayForEvent(event, delays);
    if (eventDelay > 0) {
      await new Promise<void>((resolve, reject) => {
        const abortError = new Error("Aborted");
        abortError.name = "AbortError";
        const timeout = setTimeout(() => {
          signal?.removeEventListener("abort", onAbort);
          resolve();
        }, eventDelay);
        const onAbort = () => {
          clearTimeout(timeout);
          signal?.removeEventListener("abort", onAbort);
          reject(abortError);
        };
        if (signal?.aborted) {
          onAbort();
          return;
        }
        if (signal) {
          signal.addEventListener("abort", onAbort, { once: true });
        }
      });
    }
  }
}
