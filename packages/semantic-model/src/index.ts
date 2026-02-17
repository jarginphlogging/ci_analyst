import model from "../models/banking-core.v1.json" with { type: "json" };
import { z } from "zod";

const tableSchema = z.object({
  name: z.string(),
  description: z.string(),
  dimensions: z.array(z.string()),
  metrics: z.array(z.string()),
});

const joinRuleSchema = z.object({
  left: z.string(),
  right: z.string(),
  keys: z.array(z.string()),
});

const semanticModelSchema = z.object({
  version: z.string(),
  description: z.string(),
  tables: z.array(tableSchema),
  joinRules: z.array(joinRuleSchema),
  policy: z.object({
    restrictedColumns: z.array(z.string()),
    defaultRowLimit: z.number(),
    maxRowLimit: z.number(),
  }),
});

export type SemanticModel = z.infer<typeof semanticModelSchema>;

export function loadSemanticModel(): SemanticModel {
  return semanticModelSchema.parse(model);
}

export function findMetricTable(metric: string): string | null {
  const semanticModel = loadSemanticModel();
  const table = semanticModel.tables.find((candidate) => candidate.metrics.includes(metric));
  return table?.name ?? null;
}

export function isRestrictedColumn(columnName: string): boolean {
  return loadSemanticModel().policy.restrictedColumns.includes(columnName);
}
