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

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function parseSummaryCardValue(rawValue) {
  const text = String(rawValue ?? "").trim();
  if (!text) {
    return null;
  }

  const normalized = text.replace(/,/g, "");
  let unit = "count";
  let numericText = normalized;

  if (numericText.endsWith("%")) {
    unit = "pct";
    numericText = numericText.slice(0, -1);
  } else if (/bps$/i.test(numericText)) {
    unit = "bps";
    numericText = numericText.replace(/bps$/i, "").trim();
  } else if (numericText.startsWith("$")) {
    unit = "usd";
    numericText = numericText.slice(1);
  }

  let multiplier = 1;
  if (/k$/i.test(numericText)) {
    multiplier = 1_000;
    numericText = numericText.slice(0, -1);
  } else if (/m$/i.test(numericText)) {
    multiplier = 1_000_000;
    numericText = numericText.slice(0, -1);
  } else if (/b$/i.test(numericText)) {
    multiplier = 1_000_000_000;
    numericText = numericText.slice(0, -1);
  }

  const value = Number(numericText);
  if (!Number.isFinite(value)) {
    return null;
  }

  return { value: value * multiplier, unit };
}

export function evaluateNumericAssertions(payload, assertions) {
  const summaryCards = Array.isArray(payload?.response?.summary?.summaryCards) ? payload.response.summary.summaryCards : [];
  const checks = [];
  let pass = true;

  for (const assertion of Array.isArray(assertions) ? assertions : []) {
    const label = String(assertion?.label ?? "").trim();
    const field = "value";
    const expected = Number(assertion?.expected);
    const tolerance = Number(assertion?.tolerance ?? 0);
    const expectedUnit = assertion?.unit ? String(assertion.unit) : undefined;

    const card = summaryCards.find((item) => normalize(item?.label) === normalize(label));
    if (!card) {
      pass = false;
      checks.push({
        label,
        field,
        pass: false,
        reason: "summary_card_not_found",
      });
      continue;
    }

    const parsed = parseSummaryCardValue(card.value);
    const actual = parsed?.value;
    const actualUnit = parsed?.unit ?? null;
    if (!isFiniteNumber(expected) || !isFiniteNumber(actual) || !isFiniteNumber(tolerance)) {
      pass = false;
      checks.push({
        label,
        field,
        pass: false,
        reason: "invalid_summary_card_value",
      });
      continue;
    }

    const absDiff = Math.abs(actual - expected);
    const valuePass = absDiff <= Math.max(0, tolerance);
    const unitPass = expectedUnit ? normalize(actualUnit) === normalize(expectedUnit) : true;
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
      actualUnit,
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
