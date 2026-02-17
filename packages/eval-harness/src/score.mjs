export function normalize(text) {
  return String(text ?? "").trim().toLowerCase();
}

export function scoreTokenMatch(answer, expectedTokens, minHits = 1) {
  const normalized = normalize(answer);
  const tokens = Array.isArray(expectedTokens) ? expectedTokens : [];
  const hits = tokens.filter((token) => normalized.includes(normalize(token)));
  return {
    pass: hits.length >= Math.max(1, Number(minHits) || 1),
    hitCount: hits.length,
    hits,
  };
}

export function detectRoute(payload) {
  const assumptions = payload?.response?.assumptions;
  if (!Array.isArray(assumptions)) {
    return "unknown";
  }

  for (const item of assumptions) {
    const value = normalize(item);
    if (value.includes("deep path was selected")) {
      return "deep_path";
    }
    if (value.includes("fast path was selected")) {
      return "fast_path";
    }
  }
  return "unknown";
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

export function evaluateNumericAssertions(payload, assertions) {
  const metrics = Array.isArray(payload?.response?.metrics) ? payload.response.metrics : [];
  const checks = [];
  let pass = true;

  for (const assertion of Array.isArray(assertions) ? assertions : []) {
    const label = String(assertion?.label ?? "").trim();
    const field = assertion?.field === "delta" ? "delta" : "value";
    const expected = Number(assertion?.expected);
    const tolerance = Number(assertion?.tolerance ?? 0);
    const expectedUnit = assertion?.unit ? String(assertion.unit) : undefined;

    const metric = metrics.find((item) => normalize(item?.label) === normalize(label));
    if (!metric) {
      pass = false;
      checks.push({
        label,
        field,
        pass: false,
        reason: "metric_not_found",
      });
      continue;
    }

    const actual = Number(metric[field]);
    if (!isFiniteNumber(expected) || !isFiniteNumber(actual) || !isFiniteNumber(tolerance)) {
      pass = false;
      checks.push({
        label,
        field,
        pass: false,
        reason: "invalid_numeric_values",
      });
      continue;
    }

    const absDiff = Math.abs(actual - expected);
    const valuePass = absDiff <= Math.max(0, tolerance);
    const unitPass = expectedUnit ? normalize(metric.unit) === normalize(expectedUnit) : true;
    const assertionPass = valuePass && unitPass;

    if (!assertionPass) {
      pass = false;
    }

    checks.push({
      label,
      field,
      expected,
      actual,
      tolerance,
      absDiff,
      expectedUnit: expectedUnit ?? null,
      actualUnit: metric.unit ?? null,
      pass: assertionPass,
      reason: assertionPass ? "ok" : valuePass ? "unit_mismatch" : "value_mismatch",
    });
  }

  return { pass, checks };
}

export function percentile(values, percentileRank) {
  const numbers = values.filter((value) => typeof value === "number" && Number.isFinite(value));
  if (!numbers.length) {
    return null;
  }
  const rank = Math.max(0, Math.min(100, Number(percentileRank)));
  const sorted = [...numbers].sort((a, b) => a - b);
  const index = Math.ceil((rank / 100) * sorted.length) - 1;
  return sorted[Math.max(0, Math.min(sorted.length - 1, index))];
}
