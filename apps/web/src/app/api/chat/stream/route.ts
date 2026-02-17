import { buildMockEvents, streamMockEvents } from "@/lib/mock-stream";
import { serverEnv } from "@/lib/server-env";

interface ChatRequestBody {
  sessionId?: string;
  message?: string;
}

function ndjsonHeaders(): HeadersInit {
  return {
    "Content-Type": "application/x-ndjson; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
  };
}

export async function POST(request: Request) {
  let message = "";
  let sessionId: string | undefined;

  try {
    const body = (await request.json()) as ChatRequestBody;
    message = body?.message?.trim() ?? "";
    sessionId = body?.sessionId;
  } catch {
    return new Response(`${JSON.stringify({ type: "error", message: "invalid request payload" })}\n`, {
      status: 400,
      headers: ndjsonHeaders(),
    });
  }

  if (!message) {
    return new Response(`${JSON.stringify({ type: "error", message: "message is required" })}\n`, {
      status: 400,
      headers: ndjsonHeaders(),
    });
  }

  if (!serverEnv.WEB_USE_LOCAL_MOCK && serverEnv.ORCHESTRATOR_URL) {
    try {
      const upstream = await fetch(`${serverEnv.ORCHESTRATOR_URL}/v1/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, message }),
      });

      if (!upstream.body) {
        return new Response(`${JSON.stringify({ type: "error", message: "orchestrator stream unavailable" })}\n`, {
          status: 502,
          headers: ndjsonHeaders(),
        });
      }

      return new Response(upstream.body, {
        status: upstream.status,
        headers: ndjsonHeaders(),
      });
    } catch {
      return new Response(
        `${JSON.stringify({ type: "error", message: "failed to reach orchestrator" })}\n${JSON.stringify({ type: "done" })}\n`,
        {
          status: 502,
          headers: ndjsonHeaders(),
        },
      );
    }
  }

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const encoder = new TextEncoder();
      const write = (chunk: string) => controller.enqueue(encoder.encode(chunk));

      await streamMockEvents(buildMockEvents(message), write, {
        statusMs: serverEnv.WEB_MOCK_STATUS_DELAY_MS,
        tokenMs: serverEnv.WEB_MOCK_TOKEN_DELAY_MS,
        responseMs: serverEnv.WEB_MOCK_RESPONSE_DELAY_MS,
      });
      controller.close();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: ndjsonHeaders(),
  });
}
