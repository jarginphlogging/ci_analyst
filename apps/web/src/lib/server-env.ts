function parseBoolean(value: string | undefined, fallback: boolean): boolean {
  if (!value) return fallback;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

function parseWebBackendMode(value: string | undefined): "web_mock" | "orchestrator" | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === "web_mock" || normalized === "orchestrator") {
    return normalized;
  }
  return null;
}

function parseNumber(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const parsedMode = parseWebBackendMode(process.env.WEB_BACKEND_MODE);
const legacyLocalMock = parseBoolean(process.env.WEB_USE_LOCAL_MOCK, true);
const resolvedMode = parsedMode ?? (legacyLocalMock ? "web_mock" : "orchestrator");

export const serverEnv = {
  ORCHESTRATOR_URL: process.env.ORCHESTRATOR_URL,
  WEB_BACKEND_MODE: resolvedMode,
  WEB_MOCK_STATUS_DELAY_MS: parseNumber(process.env.WEB_MOCK_STATUS_DELAY_MS, 650),
  WEB_MOCK_TOKEN_DELAY_MS: parseNumber(process.env.WEB_MOCK_TOKEN_DELAY_MS, 110),
  WEB_MOCK_RESPONSE_DELAY_MS: parseNumber(process.env.WEB_MOCK_RESPONSE_DELAY_MS, 400),
};
