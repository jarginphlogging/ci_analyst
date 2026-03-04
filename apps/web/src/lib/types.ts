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
}

export interface SummaryCard {
  label: string;
  value: string;
  detail?: string;
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
}

export interface AgentResponse {
  answer: string;
  confidence: "high" | "medium" | "low";
  confidenceReason?: string;
  whyItMatters: string;
  presentationIntent?: PresentationIntent;
  chartConfig?: ChartConfig | null;
  tableConfig?: TableConfig | null;
  metrics: MetricPoint[];
  evidence: EvidenceRow[];
  insights: Insight[];
  suggestedQuestions: string[];
  assumptions: string[];
  trace: TraceStep[];
  summaryCards?: SummaryCard[];
  primaryVisual?: PrimaryVisual;
  dataTables: DataTable[];
  artifacts?: AnalysisArtifact[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
  response?: AgentResponse;
  draftResponse?: AgentResponse;
  hasAnswerDeltas?: boolean;
  isStreaming?: boolean;
  statusUpdates?: string[];
  requestDurationMs?: number;
}

export type ChatStreamEvent =
  | { type: "status"; message: string }
  | { type: "answer_delta"; delta: string }
  | { type: "response"; response: AgentResponse; phase?: "draft" | "final" }
  | { type: "done" }
  | { type: "error"; message: string };
