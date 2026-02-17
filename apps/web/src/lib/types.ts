export type TraceStatus = "done" | "running" | "blocked";

export interface TraceStep {
  id: string;
  title: string;
  summary: string;
  status: TraceStatus;
  sql?: string;
  qualityChecks?: string[];
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

export interface AgentResponse {
  answer: string;
  confidence: "high" | "medium" | "low";
  whyItMatters: string;
  metrics: MetricPoint[];
  evidence: EvidenceRow[];
  insights: Insight[];
  suggestedQuestions: string[];
  assumptions: string[];
  trace: TraceStep[];
  dataTables: DataTable[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
  response?: AgentResponse;
  isStreaming?: boolean;
  statusUpdates?: string[];
}

export type ChatStreamEvent =
  | { type: "status"; message: string }
  | { type: "answer_delta"; delta: string }
  | { type: "response"; response: AgentResponse }
  | { type: "done" }
  | { type: "error"; message: string };
