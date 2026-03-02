import { chatTurnRequestSchema } from "@ci/contracts";
import { NextResponse } from "next/server";
import { getMockAgentResponse } from "@/lib/mock-agent";
import { serverEnv } from "@/lib/server-env";

export async function POST(request: Request) {
  try {
    const rawBody = (await request.json()) as unknown;
    const parsed = chatTurnRequestSchema.safeParse(rawBody);

    if (!parsed.success) {
      return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
    }

    const message = parsed.data.message.trim();
    const sessionId = parsed.data.sessionId;

    if (!message) {
      return NextResponse.json({ error: "message is required" }, { status: 400 });
    }

    if (serverEnv.WEB_BACKEND_MODE === "orchestrator" && serverEnv.ORCHESTRATOR_URL) {
      const upstream = await fetch(`${serverEnv.ORCHESTRATOR_URL}/v1/chat/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, message }),
      });

      const upstreamBody = await upstream.text();
      return new NextResponse(upstreamBody, {
        status: upstream.status,
        headers: {
          "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
        },
      });
    }

    const response = getMockAgentResponse(message);

    return NextResponse.json({
      turnId: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      response,
    });
  } catch {
    return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
  }
}
