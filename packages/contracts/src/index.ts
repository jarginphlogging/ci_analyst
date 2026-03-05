import { z } from "zod";

export const chatTurnRequestSchema = z.object({
  sessionId: z.string().uuid().optional(),
  message: z.string().min(1),
  role: z.string().optional(),
  explicitFilters: z.record(z.string(), z.array(z.string())).optional(),
});

export type ChatTurnRequest = z.infer<typeof chatTurnRequestSchema>;

export const traceStatusSchema = z.enum(["done", "running", "blocked"]);

export const traceStepSchema = z.object({
  id: z.string(),
  title: z.string(),
  summary: z.string(),
  status: traceStatusSchema,
  runtimeMs: z.number().nonnegative().nullable().optional(),
  sql: z.string().nullable().optional(),
  qualityChecks: z.array(z.string()).nullable().optional(),
  stageInput: z.record(z.string(), z.unknown()).nullable().optional(),
  stageOutput: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const metricPointSchema = z.object({
  label: z.string(),
  value: z.number(),
  delta: z.number(),
  unit: z.enum(["pct", "bps", "usd", "count"]),
});

export const evidenceRowSchema = z.object({
  segment: z.string(),
  prior: z.number(),
  current: z.number(),
  changeBps: z.number(),
  contribution: z.number(),
});

export const insightSchema = z.object({
  id: z.string(),
  title: z.string(),
  detail: z.string(),
  importance: z.enum(["high", "medium"]),
});

export const dataTableSchema = z.object({
  id: z.string(),
  name: z.string(),
  columns: z.array(z.string()),
  rows: z.array(z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()]))),
  rowCount: z.number().int().nonnegative(),
  description: z.string().optional(),
  sourceSql: z.string().optional(),
});

export const presentationIntentSchema = z.object({
  displayType: z.enum(["inline", "table", "chart"]),
  chartType: z.enum(["line", "bar", "stacked_bar", "stacked_area", "grouped_bar"]).nullable().optional(),
  tableStyle: z.enum(["simple", "ranked", "comparison"]).nullable().optional(),
  rationale: z.string().optional(),
  rankingObjectives: z.array(z.string()).optional(),
});

export const chartConfigSchema = z.object({
  type: z.enum(["line", "bar", "stacked_bar", "stacked_area", "grouped_bar"]),
  x: z.string(),
  y: z.union([z.string(), z.array(z.string())]),
  series: z.string().nullable().optional(),
  xLabel: z.string().optional(),
  yLabel: z.string().optional(),
  yFormat: z.enum(["currency", "number", "percent"]).optional(),
});

export const tableColumnConfigSchema = z.object({
  key: z.string(),
  label: z.string(),
  format: z.enum(["currency", "number", "percent", "date", "string"]),
  align: z.enum(["left", "right"]),
});

export const tableConfigSchema = z.object({
  style: z.enum(["simple", "ranked", "comparison"]),
  columns: z.array(tableColumnConfigSchema),
  sortBy: z.string().nullable().optional(),
  sortDir: z.enum(["asc", "desc"]).nullable().optional(),
  showRank: z.boolean().optional(),
  comparisonMode: z.enum(["baseline", "pairwise", "index"]).optional(),
  comparisonKeys: z.array(z.string()).optional(),
  baselineKey: z.string().nullable().optional(),
  deltaPolicy: z.enum(["abs", "pct", "both"]).optional(),
  maxComparandsBeforeChartSwitch: z.number().int().positive().optional(),
});

export const summaryCardSchema = z.object({
  label: z.string(),
  value: z.string(),
  detail: z.string().optional(),
});

export const salienceDriverSchema = z.enum(["intent", "magnitude", "completeness", "reliability", "period_compatibility"]);
export const supportStatusSchema = z.enum(["strong", "moderate", "weak"]);
export const evidenceStatusSchema = z.enum(["sufficient", "limited", "insufficient"]);

export const evidenceReferenceSchema = z.object({
  refType: z.enum(["fact", "comparison"]),
  refId: z.string(),
});

export const evidenceProvenanceSchema = z.object({
  stepIndex: z.number().int().positive(),
  columnRefs: z.array(z.string()).default([]),
  timeWindow: z.string().optional(),
  aggregationType: z.string().optional(),
});

export const factSignalSchema = z.object({
  id: z.string(),
  metric: z.string(),
  period: z.string(),
  value: z.number(),
  unit: z.enum(["currency", "number", "percent"]).optional(),
  grain: z.string().optional(),
  supportStatus: supportStatusSchema.optional(),
  salienceScore: z.number().optional(),
  salienceRank: z.number().int().positive().nullable().optional(),
  salienceDriver: salienceDriverSchema.nullable().optional(),
  provenance: evidenceProvenanceSchema,
});

export const comparisonSignalSchema = z.object({
  id: z.string(),
  metric: z.string(),
  priorPeriod: z.string(),
  currentPeriod: z.string(),
  priorValue: z.number(),
  currentValue: z.number(),
  absDelta: z.number(),
  pctDelta: z.number().nullable().optional(),
  compatibilityReason: z.string().optional(),
  supportStatus: supportStatusSchema.optional(),
  salienceScore: z.number().optional(),
  salienceRank: z.number().int().positive().nullable().optional(),
  salienceDriver: salienceDriverSchema.nullable().optional(),
  provenance: z.array(evidenceProvenanceSchema).default([]),
});

export const claimSupportSchema = z.object({
  claimId: z.string(),
  claimType: z.enum(["fact", "comparison"]),
  supportStatus: supportStatusSchema,
  reason: z.string().optional(),
});

export const subtaskStatusSchema = z.object({
  id: z.string(),
  status: evidenceStatusSchema,
  reason: z.string().optional(),
});

export const analysisArtifactSchema = z.object({
  id: z.string(),
  kind: z.enum(["ranking_breakdown", "comparison_breakdown", "delta_breakdown", "trend_breakdown", "distribution_breakdown"]),
  title: z.string(),
  description: z.string().optional(),
  columns: z.array(z.string()),
  rows: z.array(z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()]))),
  dimensionKey: z.string().optional(),
  valueKey: z.string().optional(),
  timeKey: z.string().optional(),
  expectedGrain: z.string().optional(),
  detectedGrain: z.string().optional(),
  evidenceRefs: z.array(evidenceReferenceSchema).optional(),
  salienceRank: z.number().int().positive().nullable().optional(),
  salienceScore: z.number().nullable().optional(),
  salienceDriver: salienceDriverSchema.nullable().optional(),
  supportStatus: supportStatusSchema.nullable().optional(),
});

export const primaryVisualSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
  visualType: z.enum(["trend", "ranking", "comparison", "distribution", "snapshot", "table"]).optional(),
  artifactKind: analysisArtifactSchema.shape.kind.optional(),
});

export const agentResponseSchema = z.object({
  answer: z.string(),
  confidence: z.enum(["high", "medium", "low"]),
  confidenceReason: z.string().optional(),
  whyItMatters: z.string(),
  presentationIntent: presentationIntentSchema.optional(),
  chartConfig: chartConfigSchema.nullable().optional(),
  tableConfig: tableConfigSchema.nullable().optional(),
  metrics: z.array(metricPointSchema),
  evidence: z.array(evidenceRowSchema),
  insights: z.array(insightSchema),
  suggestedQuestions: z.array(z.string()),
  assumptions: z.array(z.string()),
  trace: z.array(traceStepSchema),
  summaryCards: z.array(summaryCardSchema).optional(),
  primaryVisual: primaryVisualSchema.nullable().optional(),
  dataTables: z.array(dataTableSchema).default([]),
  artifacts: z.array(analysisArtifactSchema).optional(),
  facts: z.array(factSignalSchema).optional(),
  comparisons: z.array(comparisonSignalSchema).optional(),
  evidenceStatus: evidenceStatusSchema.optional(),
  evidenceEmptyReason: z.string().optional(),
  subtaskStatus: z.array(subtaskStatusSchema).optional(),
  claimSupport: z.array(claimSupportSchema).optional(),
  headline: z.string().optional(),
  headlineEvidenceRefs: z.array(evidenceReferenceSchema).optional(),
  periodStart: z.string().optional(),
  periodEnd: z.string().optional(),
  periodLabel: z.string().optional(),
});

export type AgentResponse = z.infer<typeof agentResponseSchema>;

export const chatTurnResponseSchema = z.object({
  turnId: z.string().uuid(),
  createdAt: z.string(),
  response: agentResponseSchema,
});

export type ChatTurnResponse = z.infer<typeof chatTurnResponseSchema>;

export const chatStreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("status"), message: z.string() }),
  z.object({ type: z.literal("answer_delta"), delta: z.string() }),
  z.object({ type: z.literal("response"), response: agentResponseSchema, phase: z.enum(["draft", "final"]).optional() }),
  z.object({ type: z.literal("done") }),
  z.object({ type: z.literal("error"), message: z.string() }),
]);

export type ChatStreamEvent = z.infer<typeof chatStreamEventSchema>;
