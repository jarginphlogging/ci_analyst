import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { pathToFileURL } from "node:url";
import { detectRoute, evaluateNumericAssertions, percentile, scoreTokenMatch } from "./score.mjs";

const BASE_URL = process.env.EVAL_BASE_URL ?? "http://localhost:8787";
const DATASET_PATH = process.env.EVAL_DATASET_PATH
  ? pathToFileURL(resolve(process.env.EVAL_DATASET_PATH))
  : new URL("../datasets/golden-v1.json", import.meta.url);

function asNumberOrNull(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return null;
  }
  return number;
}

function latencyBudgets() {
  return {
    fast_path: {
      p50MaxMs: asNumberOrNull(process.env.EVAL_FAST_PATH_P50_MAX_MS) ?? 2500,
      p95MaxMs: asNumberOrNull(process.env.EVAL_FAST_PATH_P95_MAX_MS) ?? 5000,
    },
    deep_path: {
      p50MaxMs: asNumberOrNull(process.env.EVAL_DEEP_PATH_P50_MAX_MS) ?? 7000,
      p95MaxMs: asNumberOrNull(process.env.EVAL_DEEP_PATH_P95_MAX_MS) ?? 15000,
    },
  };
}

function evaluateLatencyForRoute(route, latencies, budgets) {
  const p50 = percentile(latencies, 50);
  const p95 = percentile(latencies, 95);
  const budget = budgets[route];

  if (!budget) {
    return {
      route,
      sampleCount: latencies.length,
      p50Ms: p50,
      p95Ms: p95,
      p50MaxMs: null,
      p95MaxMs: null,
      pass: true,
      reason: "no_budget_configured",
    };
  }

  const p50Pass = p50 === null || budget.p50MaxMs === null || p50 <= budget.p50MaxMs;
  const p95Pass = p95 === null || budget.p95MaxMs === null || p95 <= budget.p95MaxMs;
  return {
    route,
    sampleCount: latencies.length,
    p50Ms: p50,
    p95Ms: p95,
    p50MaxMs: budget.p50MaxMs,
    p95MaxMs: budget.p95MaxMs,
    pass: p50Pass && p95Pass,
    reason: p50Pass && p95Pass ? "ok" : "latency_threshold_exceeded",
  };
}

async function run() {
  const datasetText = await readFile(DATASET_PATH, "utf8");
  const dataset = JSON.parse(datasetText);
  const budgets = latencyBudgets();

  const results = [];

  for (const item of dataset) {
    const start = performance.now();
    const response = await fetch(`${BASE_URL}/v1/chat/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: item.question }),
    });

    const elapsedMs = Math.round(performance.now() - start);

    if (!response.ok) {
      results.push({
        id: item.id,
        question: item.question,
        pass: false,
        latencyMs: elapsedMs,
        error: `HTTP ${response.status}`,
      });
      continue;
    }

    const payload = await response.json();
    const tokenMatch = scoreTokenMatch(
      payload?.response?.answer,
      item.mustContainAny,
      item.minTokenHits ?? 1,
    );
    const route = detectRoute(payload);
    const expectedRoute = item.expectedRoute ?? null;
    const routePass = expectedRoute ? route === expectedRoute : true;
    const numeric = evaluateNumericAssertions(payload, item.numericAssertions);
    const maxLatencyMs = asNumberOrNull(item.maxLatencyMs);
    const latencyPass = maxLatencyMs === null ? true : elapsedMs <= maxLatencyMs;
    const pass = tokenMatch.pass && numeric.pass && routePass && latencyPass;

    results.push({
      id: item.id,
      question: item.question,
      route,
      expectedRoute,
      pass,
      tokenMatch,
      numeric,
      latencyMs: elapsedMs,
      maxLatencyMs,
      latencyPass,
      routePass,
      confidence: payload?.response?.confidence,
      responseId: payload?.turnId ?? null,
    });
  }

  const passCount = results.filter((r) => r.pass).length;
  const avgLatency = Math.round(results.reduce((acc, item) => acc + (item.latencyMs || 0), 0) / results.length);
  const allLatencies = results.map((item) => item.latencyMs || 0);
  const routeLatencyChecks = [
    evaluateLatencyForRoute(
      "fast_path",
      results.filter((item) => item.route === "fast_path").map((item) => item.latencyMs),
      budgets,
    ),
    evaluateLatencyForRoute(
      "deep_path",
      results.filter((item) => item.route === "deep_path").map((item) => item.latencyMs),
      budgets,
    ),
  ];
  const latencyGatePass = routeLatencyChecks.every((check) => check.pass);
  const globalP50 = percentile(allLatencies, 50);
  const globalP95 = percentile(allLatencies, 95);
  const overallPass = passCount === results.length && latencyGatePass;

  console.log(JSON.stringify({
    baseUrl: BASE_URL,
    datasetPath: DATASET_PATH.pathname,
    total: results.length,
    passCount,
    passRate: Number((passCount / results.length).toFixed(2)),
    avgLatencyMs: avgLatency,
    p50LatencyMs: globalP50,
    p95LatencyMs: globalP95,
    latencyBudgets: budgets,
    routeLatencyChecks,
    overallPass,
    results,
  }, null, 2));

  if (!overallPass) {
    process.exitCode = 1;
  }
}

run().catch((error) => {
  console.error("evaluation failed", error);
  process.exit(1);
});
