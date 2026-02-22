import { serverEnv } from "@/lib/server-env";

type EnvironmentLabel = "Mock" | "Sandbox" | "Production";

function mapProviderModeToEnvironment(providerMode: unknown): EnvironmentLabel | null {
  if (typeof providerMode !== "string") return null;
  const normalized = providerMode.trim().toLowerCase();
  if (normalized === "mock") return "Mock";
  if (normalized === "sandbox") return "Sandbox";
  if (normalized === "prod" || normalized === "production") return "Production";
  return null;
}

function fallbackEnvironment(): EnvironmentLabel {
  return serverEnv.WEB_BACKEND_MODE === "web_mock" ? "Mock" : "Sandbox";
}

export async function GET() {
  const fallback = fallbackEnvironment();

  if (serverEnv.WEB_BACKEND_MODE !== "orchestrator" || !serverEnv.ORCHESTRATOR_URL) {
    return Response.json({ environment: fallback });
  }

  try {
    const upstream = await fetch(`${serverEnv.ORCHESTRATOR_URL}/health`, {
      method: "GET",
      cache: "no-store",
    });

    if (!upstream.ok) {
      return Response.json({ environment: fallback });
    }

    const body = (await upstream.json()) as { providerMode?: unknown };
    const resolved = mapProviderModeToEnvironment(body.providerMode) ?? fallback;
    return Response.json({ environment: resolved });
  } catch {
    return Response.json({ environment: fallback });
  }
}
