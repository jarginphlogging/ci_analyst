export type TraceStatus = "done" | "running" | "blocked";

export interface TraceStep {
  id: string;
  title: string;
  summary: string;
  status: TraceStatus;
  runtimeMs?: number | null;
  sql?: string;
  qualityChecks?: string[];
  stageInput?: Record<string, unknown>;
  stageOutput?: Record<string, unknown>;
}

export interface MetricPoint {
  label: string;
  value: number;
  delta: number;
  unit: "pct" | "bps" | "usd" | "count";
}

export interface EvidenceRow {
  segment: string;
  prior: number;
  current: number;
  changeBps: number;
  contribution: number;
}

export interface Insight {
  id: string;
  title: string;
  detail: string;
  importance: "high" | "medium";
}

export type DataCell = string | number | boolean | null;

export interface DataTable {
  id: string;
  name: string;
  columns: string[];
  rows: Array<Record<string, DataCell>>;
  rowCount: number;
  description?: string;
  sourceSql?: string;
}

export interface AnalysisArtifact {
  id: string;
  kind:
    | "ranking_breakdown"
    | "comparison_breakdown"
    | "delta_breakdown"
    | "trend_breakdown"
    | "distribution_breakdown";
  title: string;
  description?: string;
  columns: string[];
  rows: Array<Record<string, DataCell>>;
  dimensionKey?: string;
  valueKey?: string;
  timeKey?: string;
  expectedGrain?: string;
  detectedGrain?: string;
  evidenceRefs?: EvidenceReference[];
  salienceRank?: number | null;
  salienceScore?: number | null;
  salienceDriver?: SalienceDriver | null;
  supportStatus?: SupportStatus | null;
}

export interface SummaryCard {
  label: string;
  value: string;
  detail?: string;
}

export type SalienceDriver = "intent" | "magnitude" | "completeness" | "reliability" | "period_compatibility";
export type SupportStatus = "strong" | "moderate" | "weak";
export type EvidenceStatus = "sufficient" | "limited" | "insufficient";

export interface EvidenceReference {
  refType: "fact" | "comparison";
  refId: string;
}

export interface EvidenceProvenance {
  stepIndex: number;
  columnRefs?: string[];
  timeWindow?: string;
  aggregationType?: string;
}

export interface FactSignal {
  id: string;
  metric: string;
  period: string;
  value: number;
  unit?: "currency" | "number" | "percent";
  grain?: string;
  supportStatus?: SupportStatus;
  salienceScore?: number;
  salienceRank?: number | null;
  salienceDriver?: SalienceDriver | null;
  provenance: EvidenceProvenance;
}

export interface ComparisonSignal {
  id: string;
  metric: string;
  priorPeriod: string;
  currentPeriod: string;
  priorValue: number;
  currentValue: number;
  absDelta: number;
  pctDelta?: number | null;
  compatibilityReason?: string;
  supportStatus?: SupportStatus;
  salienceScore?: number;
  salienceRank?: number | null;
  salienceDriver?: SalienceDriver | null;
  provenance: EvidenceProvenance[];
}

export interface ClaimSupport {
  claimId: string;
  claimType: "fact" | "comparison";
  supportStatus: SupportStatus;
  reason?: string;
}

export interface SubtaskStatus {
  id: string;
  status: EvidenceStatus;
  reason?: string;
}

export interface PrimaryVisual {
  title: string;
  description?: string;
  visualType?: "trend" | "ranking" | "comparison" | "distribution" | "snapshot" | "table";
  artifactKind?: AnalysisArtifact["kind"];
}

export interface PresentationIntent {
  displayType: "inline" | "table" | "chart";
  chartType?: "line" | "bar" | "stacked_bar" | "stacked_area" | "grouped_bar" | null;
  tableStyle?: "simple" | "ranked" | "comparison" | null;
  rationale?: string;
  rankingObjectives?: string[];
}

export interface ChartConfig {
  type: "line" | "bar" | "stacked_bar" | "stacked_area" | "grouped_bar";
  x: string;
  y: string | string[];
  series?: string | null;
  xLabel?: string;
  yLabel?: string;
  yFormat?: "currency" | "number" | "percent";
}

export interface TableColumnConfig {
  key: string;
  label: string;
  format: "currency" | "number" | "percent" | "date" | "string";
  align: "left" | "right";
}

export interface TableConfig {
  style: "simple" | "ranked" | "comparison";
  columns: TableColumnConfig[];
  sortBy?: string | null;
  sortDir?: "asc" | "desc" | null;
  showRank?: boolean;
  comparisonMode?: "baseline" | "pairwise" | "index";
  comparisonKeys?: string[];
  baselineKey?: string | null;
  deltaPolicy?: "abs" | "pct" | "both";
  maxComparandsBeforeChartSwitch?: number;
}

export interface AgentResponse {
  summary: {
    answer: string;
    confidence: "high" | "medium" | "low";
    confidenceReason?: string;
    whyItMatters: string;
    summaryCards: SummaryCard[];
    insights: Insight[];
    suggestedQuestions: string[];
    assumptions: string[];
    periodStart?: string;
    periodEnd?: string;
    periodLabel?: string;
  };
  visualization: {
    chartConfig?: ChartConfig | null;
    tableConfig?: TableConfig | null;
    primaryVisual?: PrimaryVisual;
  };
  data: {
    dataTables: DataTable[];
    evidence: EvidenceRow[];
    comparisons?: ComparisonSignal[];
  };
  audit: {
    presentationIntent?: PresentationIntent;
    artifacts?: AnalysisArtifact[];
    facts?: FactSignal[];
    evidenceStatus?: EvidenceStatus;
    evidenceEmptyReason?: string;
    subtaskStatus?: SubtaskStatus[];
    claimSupport?: ClaimSupport[];
    headline?: string;
    headlineEvidenceRefs?: EvidenceReference[];
  };
  trace: TraceStep[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
  response?: AgentResponse;
  hasAnswerDeltas?: boolean;
  isStreaming?: boolean;
  statusUpdates?: string[];
  requestDurationMs?: number;
}

export type ChatStreamEvent =
  | { type: "status"; message: string }
  | { type: "answer_delta"; delta: string }
  | { type: "response"; response: AgentResponse }
  | { type: "done" }
  | { type: "error"; message: string };
