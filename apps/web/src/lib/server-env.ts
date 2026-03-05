function parseWebBackendMode(value: string | undefined): "orchestrator" | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === "orchestrator") {
    return normalized;
  }
  return null;
}

const parsedMode = parseWebBackendMode(process.env.WEB_BACKEND_MODE);
const resolvedMode = parsedMode ?? "orchestrator";

export const serverEnv = {
  ORCHESTRATOR_URL: process.env.ORCHESTRATOR_URL,
  WEB_BACKEND_MODE: resolvedMode,
};
