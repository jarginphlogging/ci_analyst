import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";

const BASE_URL = process.env.EVAL_BASE_URL ?? "http://localhost:8787";
const DATASET_PATH = new URL("../datasets/golden-v1.json", import.meta.url);

function normalize(text) {
  return String(text || "").toLowerCase();
}

function scoreMatch(answer, expectedTokens) {
  const normalized = normalize(answer);
  const hits = expectedTokens.filter((token) => normalized.includes(normalize(token)));
  return {
    hitCount: hits.length,
    pass: hits.length > 0,
    hits,
  };
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
    const match = scoreMatch(payload?.response?.answer, item.mustContainAny);

    results.push({
      id: item.id,
      question: item.question,
      pass: match.pass,
      hits: match.hits,
      latencyMs: elapsedMs,
      confidence: payload?.response?.confidence,
    });
  }

  const passCount = results.filter((r) => r.pass).length;
  const avgLatency = Math.round(results.reduce((acc, item) => acc + (item.latencyMs || 0), 0) / results.length);

  console.log(JSON.stringify({
    baseUrl: BASE_URL,
    total: results.length,
    passCount,
    passRate: Number((passCount / results.length).toFixed(2)),
    avgLatencyMs: avgLatency,
    results,
  }, null, 2));

  if (passCount < results.length) {
    process.exitCode = 1;
  }
}

run().catch((error) => {
  console.error("evaluation failed", error);
  process.exit(1);
});
