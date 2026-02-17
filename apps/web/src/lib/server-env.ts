function parseBoolean(value: string | undefined, fallback: boolean): boolean {
  if (!value) return fallback;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

function parseNumber(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const serverEnv = {
  ORCHESTRATOR_URL: process.env.ORCHESTRATOR_URL,
  WEB_USE_LOCAL_MOCK: parseBoolean(process.env.WEB_USE_LOCAL_MOCK, true),
  WEB_MOCK_STATUS_DELAY_MS: parseNumber(process.env.WEB_MOCK_STATUS_DELAY_MS, 650),
  WEB_MOCK_TOKEN_DELAY_MS: parseNumber(process.env.WEB_MOCK_TOKEN_DELAY_MS, 110),
  WEB_MOCK_RESPONSE_DELAY_MS: parseNumber(process.env.WEB_MOCK_RESPONSE_DELAY_MS, 400),
};
