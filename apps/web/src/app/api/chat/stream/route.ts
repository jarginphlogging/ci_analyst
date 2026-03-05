import { chatTurnRequestSchema } from "@ci/contracts";
import { serverEnv } from "@/lib/server-env";

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
    const rawBody = (await request.json()) as unknown;
    const parsed = chatTurnRequestSchema.safeParse(rawBody);

    if (!parsed.success) {
      return new Response(`${JSON.stringify({ type: "error", message: "invalid request payload" })}\n`, {
        status: 400,
        headers: ndjsonHeaders(),
      });
    }

    message = parsed.data.message.trim();
    sessionId = parsed.data.sessionId;
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

  if (!serverEnv.ORCHESTRATOR_URL) {
    return new Response(`${JSON.stringify({ type: "error", message: "orchestrator url is not configured" })}\n`, {
      status: 500,
      headers: ndjsonHeaders(),
    });
  }

  try {
    const upstream = await fetch(`${serverEnv.ORCHESTRATOR_URL}/v1/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, message }),
      signal: request.signal,
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
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return new Response(null, {
        status: 204,
        headers: { "Cache-Control": "no-cache, no-transform" },
      });
    }
    return new Response(
      `${JSON.stringify({ type: "error", message: "failed to reach orchestrator" })}\n${JSON.stringify({ type: "done" })}\n`,
      {
        status: 502,
        headers: ndjsonHeaders(),
      },
    );
  }
}
