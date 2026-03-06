"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.chatStreamEventSchema = exports.chatTurnResponseSchema = exports.agentResponseSchema = exports.primaryVisualSchema = exports.analysisArtifactSchema = exports.subtaskStatusSchema = exports.claimSupportSchema = exports.comparisonSignalSchema = exports.factSignalSchema = exports.evidenceProvenanceSchema = exports.evidenceReferenceSchema = exports.evidenceStatusSchema = exports.supportStatusSchema = exports.salienceDriverSchema = exports.summaryCardSchema = exports.tableConfigSchema = exports.tableColumnConfigSchema = exports.chartConfigSchema = exports.presentationIntentSchema = exports.dataTableSchema = exports.insightSchema = exports.evidenceRowSchema = exports.metricPointSchema = exports.traceStepSchema = exports.traceStatusSchema = exports.chatTurnRequestSchema = void 0;
const zod_1 = require("zod");
exports.chatTurnRequestSchema = zod_1.z.object({
    sessionId: zod_1.z.string().uuid().optional(),
    message: zod_1.z.string().min(1),
    role: zod_1.z.string().optional(),
    explicitFilters: zod_1.z.record(zod_1.z.string(), zod_1.z.array(zod_1.z.string())).optional(),
});
exports.traceStatusSchema = zod_1.z.enum(["done", "running", "blocked"]);
exports.traceStepSchema = zod_1.z.object({
    id: zod_1.z.string(),
    title: zod_1.z.string(),
    summary: zod_1.z.string(),
    status: exports.traceStatusSchema,
    runtimeMs: zod_1.z.number().nonnegative().nullable().optional(),
    sql: zod_1.z.string().nullable().optional(),
    qualityChecks: zod_1.z.array(zod_1.z.string()).nullable().optional(),
    stageInput: zod_1.z.record(zod_1.z.string(), zod_1.z.unknown()).nullable().optional(),
    stageOutput: zod_1.z.record(zod_1.z.string(), zod_1.z.unknown()).nullable().optional(),
});
exports.metricPointSchema = zod_1.z.object({
    label: zod_1.z.string(),
    value: zod_1.z.number(),
    delta: zod_1.z.number(),
    unit: zod_1.z.enum(["pct", "bps", "usd", "count"]),
});
exports.evidenceRowSchema = zod_1.z.object({
    segment: zod_1.z.string(),
    prior: zod_1.z.number(),
    current: zod_1.z.number(),
    changeBps: zod_1.z.number(),
    contribution: zod_1.z.number(),
});
exports.insightSchema = zod_1.z.object({
    id: zod_1.z.string(),
    title: zod_1.z.string(),
    detail: zod_1.z.string(),
    importance: zod_1.z.enum(["high", "medium"]),
});
exports.dataTableSchema = zod_1.z.object({
    id: zod_1.z.string(),
    name: zod_1.z.string(),
    columns: zod_1.z.array(zod_1.z.string()),
    rows: zod_1.z.array(zod_1.z.record(zod_1.z.string(), zod_1.z.union([zod_1.z.string(), zod_1.z.number(), zod_1.z.boolean(), zod_1.z.null()]))),
    rowCount: zod_1.z.number().int().nonnegative(),
    description: zod_1.z.string().optional(),
    sourceSql: zod_1.z.string().optional(),
});
exports.presentationIntentSchema = zod_1.z.object({
    displayType: zod_1.z.enum(["inline", "table", "chart"]),
    chartType: zod_1.z.enum(["line", "bar", "stacked_bar", "stacked_area", "grouped_bar"]).nullable().optional(),
    tableStyle: zod_1.z.enum(["simple", "ranked", "comparison"]).nullable().optional(),
    rationale: zod_1.z.string().optional(),
    rankingObjectives: zod_1.z.array(zod_1.z.string()).optional(),
});
exports.chartConfigSchema = zod_1.z.object({
    type: zod_1.z.enum(["line", "bar", "stacked_bar", "stacked_area", "grouped_bar"]),
    x: zod_1.z.string(),
    y: zod_1.z.union([zod_1.z.string(), zod_1.z.array(zod_1.z.string())]),
    series: zod_1.z.string().nullable().optional(),
    xLabel: zod_1.z.string().optional(),
    yLabel: zod_1.z.string().optional(),
    yFormat: zod_1.z.enum(["currency", "number", "percent"]).optional(),
});
exports.tableColumnConfigSchema = zod_1.z.object({
    key: zod_1.z.string(),
    label: zod_1.z.string(),
    format: zod_1.z.enum(["currency", "number", "percent", "date", "string"]),
    align: zod_1.z.enum(["left", "right"]),
});
exports.tableConfigSchema = zod_1.z.object({
    style: zod_1.z.enum(["simple", "ranked", "comparison"]),
    columns: zod_1.z.array(exports.tableColumnConfigSchema),
    sortBy: zod_1.z.string().nullable().optional(),
    sortDir: zod_1.z.enum(["asc", "desc"]).nullable().optional(),
    showRank: zod_1.z.boolean().optional(),
    comparisonMode: zod_1.z.enum(["baseline", "pairwise", "index"]).optional(),
    comparisonKeys: zod_1.z.array(zod_1.z.string()).optional(),
    baselineKey: zod_1.z.string().nullable().optional(),
    deltaPolicy: zod_1.z.enum(["abs", "pct", "both"]).optional(),
    maxComparandsBeforeChartSwitch: zod_1.z.number().int().positive().optional(),
});
exports.summaryCardSchema = zod_1.z.object({
    label: zod_1.z.string(),
    value: zod_1.z.string(),
    detail: zod_1.z.string().optional(),
});
exports.salienceDriverSchema = zod_1.z.enum(["intent", "magnitude", "completeness", "reliability", "period_compatibility"]);
exports.supportStatusSchema = zod_1.z.enum(["strong", "moderate", "weak"]);
exports.evidenceStatusSchema = zod_1.z.enum(["sufficient", "limited", "insufficient"]);
exports.evidenceReferenceSchema = zod_1.z.object({
    refType: zod_1.z.enum(["fact", "comparison"]),
    refId: zod_1.z.string(),
});
exports.evidenceProvenanceSchema = zod_1.z.object({
    stepIndex: zod_1.z.number().int().positive(),
    columnRefs: zod_1.z.array(zod_1.z.string()).default([]),
    timeWindow: zod_1.z.string().optional(),
    aggregationType: zod_1.z.string().optional(),
});
exports.factSignalSchema = zod_1.z.object({
    id: zod_1.z.string(),
    metric: zod_1.z.string(),
    period: zod_1.z.string(),
    value: zod_1.z.number(),
    unit: zod_1.z.enum(["currency", "number", "percent"]).optional(),
    grain: zod_1.z.string().optional(),
    supportStatus: exports.supportStatusSchema.optional(),
    salienceScore: zod_1.z.number().optional(),
    salienceRank: zod_1.z.number().int().positive().nullable().optional(),
    salienceDriver: exports.salienceDriverSchema.nullable().optional(),
    provenance: exports.evidenceProvenanceSchema,
});
exports.comparisonSignalSchema = zod_1.z.object({
    id: zod_1.z.string(),
    metric: zod_1.z.string(),
    priorPeriod: zod_1.z.string(),
    currentPeriod: zod_1.z.string(),
    priorValue: zod_1.z.number(),
    currentValue: zod_1.z.number(),
    absDelta: zod_1.z.number(),
    pctDelta: zod_1.z.number().nullable().optional(),
    compatibilityReason: zod_1.z.string().optional(),
    supportStatus: exports.supportStatusSchema.optional(),
    salienceScore: zod_1.z.number().optional(),
    salienceRank: zod_1.z.number().int().positive().nullable().optional(),
    salienceDriver: exports.salienceDriverSchema.nullable().optional(),
    provenance: zod_1.z.array(exports.evidenceProvenanceSchema).default([]),
});
exports.claimSupportSchema = zod_1.z.object({
    claimId: zod_1.z.string(),
    claimType: zod_1.z.enum(["fact", "comparison"]),
    supportStatus: exports.supportStatusSchema,
    reason: zod_1.z.string().optional(),
});
exports.subtaskStatusSchema = zod_1.z.object({
    id: zod_1.z.string(),
    status: exports.evidenceStatusSchema,
    reason: zod_1.z.string().optional(),
});
exports.analysisArtifactSchema = zod_1.z.object({
    id: zod_1.z.string(),
    kind: zod_1.z.enum(["ranking_breakdown", "comparison_breakdown", "delta_breakdown", "trend_breakdown", "distribution_breakdown"]),
    title: zod_1.z.string(),
    description: zod_1.z.string().optional(),
    columns: zod_1.z.array(zod_1.z.string()),
    rows: zod_1.z.array(zod_1.z.record(zod_1.z.string(), zod_1.z.union([zod_1.z.string(), zod_1.z.number(), zod_1.z.boolean(), zod_1.z.null()]))),
    dimensionKey: zod_1.z.string().optional(),
    valueKey: zod_1.z.string().optional(),
    timeKey: zod_1.z.string().optional(),
    expectedGrain: zod_1.z.string().optional(),
    detectedGrain: zod_1.z.string().optional(),
    evidenceRefs: zod_1.z.array(exports.evidenceReferenceSchema).optional(),
    salienceRank: zod_1.z.number().int().positive().nullable().optional(),
    salienceScore: zod_1.z.number().nullable().optional(),
    salienceDriver: exports.salienceDriverSchema.nullable().optional(),
    supportStatus: exports.supportStatusSchema.nullable().optional(),
});
exports.primaryVisualSchema = zod_1.z.object({
    title: zod_1.z.string(),
    description: zod_1.z.string().optional(),
    visualType: zod_1.z.enum(["trend", "ranking", "comparison", "distribution", "snapshot", "table"]).optional(),
    artifactKind: exports.analysisArtifactSchema.shape.kind.optional(),
});
exports.agentResponseSchema = zod_1.z.object({
    answer: zod_1.z.string(),
    confidence: zod_1.z.enum(["high", "medium", "low"]),
    confidenceReason: zod_1.z.string().optional(),
    whyItMatters: zod_1.z.string(),
    presentationIntent: exports.presentationIntentSchema.optional(),
    chartConfig: exports.chartConfigSchema.nullable().optional(),
    tableConfig: exports.tableConfigSchema.nullable().optional(),
    metrics: zod_1.z.array(exports.metricPointSchema),
    evidence: zod_1.z.array(exports.evidenceRowSchema),
    insights: zod_1.z.array(exports.insightSchema),
    suggestedQuestions: zod_1.z.array(zod_1.z.string()),
    assumptions: zod_1.z.array(zod_1.z.string()),
    trace: zod_1.z.array(exports.traceStepSchema),
    summaryCards: zod_1.z.array(exports.summaryCardSchema).optional(),
    primaryVisual: exports.primaryVisualSchema.nullable().optional(),
    dataTables: zod_1.z.array(exports.dataTableSchema).default([]),
    artifacts: zod_1.z.array(exports.analysisArtifactSchema).optional(),
    facts: zod_1.z.array(exports.factSignalSchema).optional(),
    comparisons: zod_1.z.array(exports.comparisonSignalSchema).optional(),
    evidenceStatus: exports.evidenceStatusSchema.optional(),
    evidenceEmptyReason: zod_1.z.string().optional(),
    subtaskStatus: zod_1.z.array(exports.subtaskStatusSchema).optional(),
    claimSupport: zod_1.z.array(exports.claimSupportSchema).optional(),
    headline: zod_1.z.string().optional(),
    headlineEvidenceRefs: zod_1.z.array(exports.evidenceReferenceSchema).optional(),
    periodStart: zod_1.z.string().optional(),
    periodEnd: zod_1.z.string().optional(),
    periodLabel: zod_1.z.string().optional(),
});
exports.chatTurnResponseSchema = zod_1.z.object({
    turnId: zod_1.z.string().uuid(),
    createdAt: zod_1.z.string(),
    response: exports.agentResponseSchema,
});
exports.chatStreamEventSchema = zod_1.z.discriminatedUnion("type", [
    zod_1.z.object({ type: zod_1.z.literal("status"), message: zod_1.z.string() }),
    zod_1.z.object({ type: zod_1.z.literal("answer_delta"), delta: zod_1.z.string() }),
    zod_1.z.object({ type: zod_1.z.literal("response"), response: exports.agentResponseSchema }),
    zod_1.z.object({ type: zod_1.z.literal("done") }),
    zod_1.z.object({ type: zod_1.z.literal("error"), message: zod_1.z.string() }),
]);
