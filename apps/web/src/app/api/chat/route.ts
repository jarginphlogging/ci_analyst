import { chatTurnRequestSchema } from "@ci/contracts";
import { NextResponse } from "next/server";
import { serverEnv } from "@/lib/server-env";

export async function POST(request: Request) {
  let message = "";
  let sessionId: string | undefined;

  try {
    const rawBody = (await request.json()) as unknown;
    const parsed = chatTurnRequestSchema.safeParse(rawBody);

    if (!parsed.success) {
      return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
    }

    message = parsed.data.message.trim();
    sessionId = parsed.data.sessionId;

    if (!message) {
      return NextResponse.json({ error: "message is required" }, { status: 400 });
    }
  } catch {
    return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
  }

  if (!serverEnv.ORCHESTRATOR_URL) {
    return NextResponse.json({ error: "orchestrator url is not configured" }, { status: 500 });
  }

  try {
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
  } catch {
    return NextResponse.json({ error: "failed to reach orchestrator" }, { status: 502 });
  }
}
