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
  sql: z.string().optional(),
  qualityChecks: z.array(z.string()).optional(),
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

export const agentResponseSchema = z.object({
  answer: z.string(),
  confidence: z.enum(["high", "medium", "low"]),
  whyItMatters: z.string(),
  metrics: z.array(metricPointSchema),
  evidence: z.array(evidenceRowSchema),
  insights: z.array(insightSchema),
  suggestedQuestions: z.array(z.string()),
  assumptions: z.array(z.string()),
  trace: z.array(traceStepSchema),
  dataTables: z.array(dataTableSchema).default([]),
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
  z.object({ type: z.literal("response"), response: agentResponseSchema }),
  z.object({ type: z.literal("done") }),
  z.object({ type: z.literal("error"), message: z.string() }),
]);

export type ChatStreamEvent = z.infer<typeof chatStreamEventSchema>;
