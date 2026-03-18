import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { pathToFileURL } from "node:url";
import { evaluateNumericAssertions, percentile, scoreTokenMatch } from "./score.mjs";

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

async function run() {
  const datasetText = await readFile(DATASET_PATH, "utf8");
  const dataset = JSON.parse(datasetText);

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
      payload?.response?.summary?.answer,
      item.mustContainAny,
      item.minTokenHits ?? 1,
    );
    const numeric = evaluateNumericAssertions(payload, item.numericAssertions);
    const maxLatencyMs = asNumberOrNull(item.maxLatencyMs);
    const latencyPass = maxLatencyMs === null ? true : elapsedMs <= maxLatencyMs;
    const pass = tokenMatch.pass && numeric.pass && latencyPass;

    results.push({
      id: item.id,
      question: item.question,
      pass,
      tokenMatch,
      numeric,
      latencyMs: elapsedMs,
      maxLatencyMs,
      latencyPass,
      confidence: payload?.response?.summary?.confidence,
      responseId: payload?.turnId ?? null,
    });
  }

  const passCount = results.filter((r) => r.pass).length;
  const avgLatency = Math.round(results.reduce((acc, item) => acc + (item.latencyMs || 0), 0) / results.length);
  const allLatencies = results.map((item) => item.latencyMs || 0);
  const globalP50 = percentile(allLatencies, 50);
  const globalP95 = percentile(allLatencies, 95);
  const overallPass = passCount === results.length;

  console.log(JSON.stringify({
    baseUrl: BASE_URL,
    datasetPath: DATASET_PATH.pathname,
    total: results.length,
    passCount,
    passRate: Number((passCount / results.length).toFixed(2)),
    avgLatencyMs: avgLatency,
    p50LatencyMs: globalP50,
    p95LatencyMs: globalP95,
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
