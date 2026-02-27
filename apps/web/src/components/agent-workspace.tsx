"use client";

import { useEffect, useMemo, useState } from "react";
import { AnalysisTrace } from "@/components/analysis-trace";
import { DataExplorer } from "@/components/data-explorer";
import { EvidenceTable } from "@/components/evidence-table";
import { readNdjsonStream } from "@/lib/stream";
import type { AgentResponse, ChatMessage, ChatStreamEvent, DataTable, MetricPoint, SummaryCard } from "@/lib/types";

const starterPrompts = [
  "Show me my sales in each state in descending order.",
  "What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?",
  "What are my top and bottom performing stores for 2025? Include new vs repeat mix and compare to prior year.",
];

const sessionItems = [
  "State Sales Taxonomy",
  "Q4 YoY Performance",
  "Store Performance Monitor",
  "Channel Mix Deep Dive",
];

const insightImportanceRank: Record<"high" | "medium", number> = {
  high: 0,
  medium: 1,
};

const integerFormatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const currencyFormatter = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const dateFormatter = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
type KpiMetric = Pick<MetricPoint, "label" | "value" | "unit">;

function toTitleCase(text: string): string {
  return text.toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
}

function normalizeMetricLabel(label: string): string {
  const cleaned = label.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  if (!cleaned) return label;

  const dedupedWords = cleaned.split(" ").filter((word, index, words) => {
    if (index === 0) return true;
    return word.toLowerCase() !== words[index - 1].toLowerCase();
  });
  const deduped = dedupedWords.join(" ");

  return deduped === deduped.toUpperCase() ? toTitleCase(deduped) : deduped;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function looksCurrencyLabel(label: string): boolean {
  return /(spend|sales|revenue|amount|ticket|value|aov)/i.test(label);
}

function looksPercentLabel(label: string): boolean {
  return /(share|percent|percentage|ratio|rate|mix|pct)/i.test(label);
}

function isRowsRetrievedLabel(label: string): boolean {
  return normalizeMetricLabel(label).toLowerCase() === "rows retrieved";
}

function resolveMetricUnit(metric: KpiMetric): MetricPoint["unit"] {
  if (metric.unit !== "count") return metric.unit;
  if (looksPercentLabel(metric.label)) return "pct";
  if (looksCurrencyLabel(metric.label)) return "usd";
  return "count";
}

function formatUsdValue(value: number, label: string): string {
  const abs = Math.abs(value);
  const isAverageLike = /(avg|average|mean|ticket|amount)/i.test(label);

  if (abs < 1000 && !isAverageLike) return `$${value.toFixed(2)}B`;
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return currencyFormatter.format(value);
}

function formatMetric(metric: KpiMetric): string {
  const resolvedUnit = resolveMetricUnit(metric);

  if (resolvedUnit === "pct") {
    const normalizedPct = Math.abs(metric.value) <= 1 ? metric.value * 100 : metric.value;
    return `${normalizedPct.toFixed(Math.abs(normalizedPct) >= 10 ? 1 : 2)}%`;
  }
  if (resolvedUnit === "bps") return `${metric.value.toFixed(0)} bps`;
  if (resolvedUnit === "usd") return formatUsdValue(metric.value, metric.label);
  return integerFormatter.format(Math.round(metric.value));
}

function derivedKpis(response: AgentResponse): KpiMetric[] {
  const fallback: KpiMetric[] = [];

  const topContribution = response.evidence.reduce((max, row) => Math.max(max, Math.abs(row.contribution)), 0);
  if (topContribution > 0) {
    fallback.push({ label: "Top Driver Share", value: topContribution * 100, unit: "pct" });
  }

  const rankingArtifact = (response.artifacts ?? []).find((artifact) => artifact.kind === "ranking_breakdown" && artifact.rows.length > 0);
  if (rankingArtifact) {
    const maxShare = Math.max(
      0,
      ...rankingArtifact.rows
        .map((row) => asFiniteNumber(row.share_pct))
        .filter((value): value is number => value !== null),
    );
    if (maxShare > 0) {
      fallback.push({ label: "Top Entity Share", value: maxShare, unit: "pct" });
    }
  }

  const highPriorityCount = response.insights.filter((insight) => insight.importance === "high").length;
  if (highPriorityCount > 0) {
    fallback.push({ label: "High-Priority Insights", value: highPriorityCount, unit: "count" });
  }

  if (response.suggestedQuestions.length > 0) {
    fallback.push({ label: "Suggested Next Steps", value: response.suggestedQuestions.length, unit: "count" });
  }

  return fallback;
}

function kpiMetrics(response: AgentResponse): KpiMetric[] {
  const primary = response.metrics.filter((metric) => !isRowsRetrievedLabel(metric.label));
  const selected: KpiMetric[] = [...primary];

  for (const metric of derivedKpis(response)) {
    if (selected.length >= 3) break;
    if (selected.some((item) => normalizeMetricLabel(item.label) === normalizeMetricLabel(metric.label))) continue;
    selected.push(metric);
  }

  return selected.slice(0, 3);
}

function summaryCardsForResponse(response: AgentResponse): SummaryCard[] {
  const fromContract = (response.summaryCards ?? [])
    .map((card) => ({
      label: (card.label ?? "").trim(),
      value: (card.value ?? "").trim(),
      detail: (card.detail ?? "").trim(),
    }))
    .filter((card) => card.label && card.value)
    .slice(0, 3);
  if (fromContract.length > 0) return fromContract;

  return kpiMetrics(response).map((metric) => ({
    label: normalizeMetricLabel(metric.label),
    value: formatMetric(metric),
    detail: "",
  }));
}

function parseDateValue(value: unknown): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value !== "string") return null;

  const trimmed = value.trim();
  if (!trimmed) return null;
  const dateOnlyMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnlyMatch) {
    const year = Number(dateOnlyMatch[1]);
    const month = Number(dateOnlyMatch[2]);
    const day = Number(dateOnlyMatch[3]);
    const localDate = new Date(year, month - 1, day);
    if (
      Number.isNaN(localDate.getTime()) ||
      localDate.getFullYear() !== year ||
      localDate.getMonth() !== month - 1 ||
      localDate.getDate() !== day
    ) {
      return null;
    }
    return localDate;
  }
  if (!/\d{4}-\d{2}-\d{2}/.test(trimmed)) return null;

  const parsed = new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDateRange(start: Date, end: Date): string {
  const from = start.getTime() <= end.getTime() ? start : end;
  const to = start.getTime() <= end.getTime() ? end : start;
  if (from.getTime() === to.getTime()) return `Period: ${dateFormatter.format(from)}`;
  return `Period: ${dateFormatter.format(from)} - ${dateFormatter.format(to)}`;
}

function periodFromSql(sql: string | undefined): string | null {
  if (!sql) return null;

  const betweenMatch = sql.match(/between\s+'(\d{4}-\d{2}-\d{2})'\s+and\s+'(\d{4}-\d{2}-\d{2})'/i);
  if (betweenMatch) {
    const start = parseDateValue(betweenMatch[1]);
    const end = parseDateValue(betweenMatch[2]);
    if (start && end) return formatDateRange(start, end);
  }

  const yearMatch = sql.match(/year\s*\(\s*resp_date\s*\)\s*=\s*(20\d{2})/i);
  if (yearMatch) {
    return `Period: Calendar year ${yearMatch[1]}`;
  }

  return null;
}

function periodFromTables(tables: DataTable[]): string | null {
  const dates: Date[] = [];

  for (const table of tables) {
    for (const row of table.rows) {
      for (const value of Object.values(row)) {
        const parsed = parseDateValue(value);
        if (parsed) {
          dates.push(parsed);
        }
      }
    }
  }

  if (dates.length === 0) return null;
  const minDate = new Date(Math.min(...dates.map((value) => value.getTime())));
  const maxDate = new Date(Math.max(...dates.map((value) => value.getTime())));
  if (minDate.getTime() === maxDate.getTime()) {
    return `As of ${dateFormatter.format(maxDate)}`;
  }
  return formatDateRange(minDate, maxDate);
}

function periodFromText(text: string): string | null {
  const betweenMatch = text.match(/(\d{4}-\d{2}-\d{2}).*?(\d{4}-\d{2}-\d{2})/i);
  if (betweenMatch) {
    const start = parseDateValue(betweenMatch[1]);
    const end = parseDateValue(betweenMatch[2]);
    if (start && end) return formatDateRange(start, end);
  }

  const quarterComparisons = [...text.matchAll(/\bq([1-4])\s*(20\d{2})\b/gi)];
  if (quarterComparisons.length >= 2) {
    const latest = quarterComparisons[0];
    const prior = quarterComparisons[1];
    return `Period: Q${latest[1]} ${latest[2]} vs Q${prior[1]} ${prior[2]}`;
  }
  if (quarterComparisons.length === 1) {
    const [quarter] = quarterComparisons;
    return `Period: Q${quarter[1]} ${quarter[2]}`;
  }

  const years = [...text.matchAll(/\b(20\d{2})\b/g)].map((match) => Number(match[1])).filter((year) => Number.isFinite(year));
  if (years.length >= 2) {
    const sorted = [...years].sort((a, b) => b - a);
    if (sorted[0] !== sorted[1]) return `Period: ${sorted[0]} vs ${sorted[1]}`;
  }
  if (years.length === 1) {
    return `Period: Calendar year ${years[0]}`;
  }

  return null;
}

function periodFromMetricLabels(metrics: MetricPoint[]): string | null {
  for (const metric of metrics) {
    const fromMetric = periodFromText(metric.label);
    if (fromMetric) return fromMetric;
  }

  return null;
}

function deriveMetricPeriodLabel(response: AgentResponse, userQuery: string, responseCreatedAt: string): string {
  for (const table of response.dataTables ?? []) {
    const fromSql = periodFromSql(table.sourceSql);
    if (fromSql) return fromSql;
  }

  for (const step of response.trace ?? []) {
    const fromTraceSql = periodFromSql(step.sql);
    if (fromTraceSql) return fromTraceSql;
  }

  const fromTables = periodFromTables(response.dataTables ?? []);
  if (fromTables) return fromTables;

  for (const assumption of response.assumptions ?? []) {
    const fromAssumption = periodFromText(assumption);
    if (fromAssumption) return fromAssumption;
  }

  const fromAnswer = periodFromText(response.answer ?? "");
  if (fromAnswer) return fromAnswer;

  const fromMetricLabels = periodFromMetricLabels(response.metrics ?? []);
  if (fromMetricLabels) return fromMetricLabels;

  const fromUserQuery = periodFromText(userQuery);
  if (fromUserQuery) return fromUserQuery;

  const responseDate = parseDateValue(responseCreatedAt);
  if (responseDate) return `As of ${dateFormatter.format(responseDate)}`;
  return `As of ${dateFormatter.format(new Date())}`;
}

function rowsRetrievedCount(response: AgentResponse): number {
  const fromTables = (response.dataTables ?? []).reduce((total, table) => total + table.rowCount, 0);
  if (fromTables > 0) return fromTables;
  return response.evidence.length;
}

function formatRuntime(durationMs: number | undefined, isStreaming: boolean | undefined): string {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs <= 0) {
    return isStreaming ? "Running..." : "--";
  }
  if (durationMs < 1000) return `${Math.round(durationMs)} ms`;
  if (durationMs < 10000) return `${(durationMs / 1000).toFixed(1)} s`;
  if (durationMs < 60000) return `${Math.round(durationMs / 1000)} s`;

  const minutes = Math.floor(durationMs / 60000);
  const seconds = Math.round((durationMs % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function nextActionBody(questions: string[] | undefined): string {
  const primary = questions?.[0]?.trim();
  if (primary) return primary;
  return "Ask a follow-up question to continue the analysis.";
}

function messageTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function buildRenderableTables(response: AgentResponse): DataTable[] {
  const tables = [...(response.dataTables ?? [])];
  if (tables.length > 0) {
    return tables;
  }

  return [
    {
      id: "evidence_fallback",
      name: "Evidence Table",
      columns: ["segment", "prior", "current", "changeBps", "contribution"],
      rows: response.evidence.map((row) => ({
        segment: row.segment,
        prior: row.prior,
        current: row.current,
        changeBps: row.changeBps,
        contribution: row.contribution,
      })),
      rowCount: response.evidence.length,
      description: "Fallback table derived from rendered evidence rows.",
    },
  ];
}

function isFailureResponse(response: AgentResponse): boolean {
  return (response.trace ?? []).some((step) => step.status === "blocked");
}

type EnvironmentLabel = "Mock" | "Sandbox" | "Production";

interface AgentWorkspaceProps {
  initialEnvironment: EnvironmentLabel;
}

function isEnvironmentLabel(value: unknown): value is EnvironmentLabel {
  return value === "Mock" || value === "Sandbox" || value === "Production";
}

export function AgentWorkspace({ initialEnvironment }: AgentWorkspaceProps) {
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [environment, setEnvironment] = useState<EnvironmentLabel>(initialEnvironment);
  const [sessionId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      text: "Ask any Customer Insights question across Sales, Loyalty, Demographics, Geographics, or Industry. I will return key insights, exportable data, and an audited trace.",
      createdAt: new Date().toISOString(),
    },
  ]);

  const latestResponse = useMemo(
    () => [...messages].reverse().find((message) => message.role === "assistant" && message.response)?.response,
    [messages],
  );
  const latestResponseIsFailure = useMemo(
    () => (latestResponse ? isFailureResponse(latestResponse) : false),
    [latestResponse],
  );
  const latestNextAction = useMemo(() => nextActionBody(latestResponse?.suggestedQuestions), [latestResponse]);
  const showStarterPrompts = useMemo(() => !messages.some((message) => message.role === "user"), [messages]);

  useEffect(() => {
    let isMounted = true;

    const loadEnvironment = async (): Promise<void> => {
      try {
        const response = await fetch("/api/system-status", { cache: "no-store" });
        if (!response.ok) return;
        const payload = (await response.json()) as { environment?: unknown };
        if (!isMounted || !isEnvironmentLabel(payload.environment)) return;
        setEnvironment(payload.environment);
      } catch {
        // Keep initial environment when status endpoint is unavailable.
      }
    };

    void loadEnvironment();
    return () => {
      isMounted = false;
    };
  }, []);

  const updateAssistantMessage = (messageId: string, updater: (draft: ChatMessage) => ChatMessage): void => {
    setMessages((prev) =>
      prev.map((message) => {
        if (message.id !== messageId) return message;
        return updater(message);
      }),
    );
  };

  async function submitQuery(query: string) {
    const clean = query.trim();
    if (!clean || isLoading) return;
    const requestStartedAtMs = performance.now();

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: clean,
      createdAt: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    const assistantMessageId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      {
        id: assistantMessageId,
        role: "assistant",
        text: "",
        createdAt: new Date().toISOString(),
        isStreaming: true,
        statusUpdates: [],
      },
    ]);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, message: clean }),
      });

      if (!response.ok || !response.body) {
        throw new Error("Request failed");
      }

      await readNdjsonStream(response.body, (event: ChatStreamEvent) => {
        if (event.type === "status") {
          updateAssistantMessage(assistantMessageId, (draft) => {
            const updates = draft.statusUpdates ?? [];
            const lastStatus = updates.length > 0 ? updates[updates.length - 1] : "";
            if (lastStatus === event.message) {
              return draft;
            }
            return {
              ...draft,
              statusUpdates: [...updates, event.message],
            };
          });
          return;
        }

        if (event.type === "answer_delta") {
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            text: `${draft.hasAnswerDeltas ? draft.text : ""}${event.delta}`,
            hasAnswerDeltas: true,
          }));
          return;
        }

        if (event.type === "response") {
          if (event.phase === "draft") {
            updateAssistantMessage(assistantMessageId, (draft) => ({
              ...draft,
              draftResponse: event.response,
            }));
            return;
          }

          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            text: event.response.answer,
            response: event.response,
            draftResponse: undefined,
            hasAnswerDeltas: true,
            requestDurationMs: Math.max(1, Math.round(performance.now() - requestStartedAtMs)),
          }));
          return;
        }

        if (event.type === "error") {
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            text: event.message,
            isStreaming: false,
            statusUpdates: [...(draft.statusUpdates ?? []), "Request failed"],
            requestDurationMs: Math.max(1, Math.round(performance.now() - requestStartedAtMs)),
          }));
          return;
        }

        if (event.type === "done") {
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            isStreaming: false,
            requestDurationMs: draft.requestDurationMs ?? Math.max(1, Math.round(performance.now() - requestStartedAtMs)),
          }));
        }
      });
    } catch {
      updateAssistantMessage(assistantMessageId, (draft) => ({
        ...draft,
        text: "I could not process that request. Please retry in a moment.",
        isStreaming: false,
        statusUpdates: [...(draft.statusUpdates ?? []), "Request failed"],
        requestDurationMs: Math.max(1, Math.round(performance.now() - requestStartedAtMs)),
      }));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[radial-gradient(circle_at_10%_10%,#d7f5ff_0,#f5f2e9_38%,#eff4f8_100%)]">
      <div className="pointer-events-none absolute -left-24 top-12 h-80 w-80 rounded-full bg-cyan-300/40 blur-3xl" />
      <div className="pointer-events-none absolute right-10 top-36 h-72 w-72 rounded-full bg-orange-200/50 blur-3xl" />

      <div className="mx-auto grid w-full max-w-[1500px] grid-cols-1 gap-5 px-4 py-5 lg:grid-cols-[260px_minmax(0,1fr)_320px] lg:px-6 lg:py-6">
        <aside className="rounded-3xl border border-slate-200 bg-slate-900 p-4 text-slate-100 shadow-[0_20px_50px_rgba(15,23,42,0.3)]">
          <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">Customer Insights</p>
          <h1 className="mt-2 text-3xl font-bold leading-tight">Analyst</h1>
          <p className="mt-2 text-sm text-slate-300">Ask questions about your data in natural language.</p>

          <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-800/70 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-400">System Status</p>
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              {environment}
            </div>
          </div>

          <div className="mt-6">
            <p className="text-xs uppercase tracking-wide text-slate-400">Sessions</p>
            <ul className="mt-3 space-y-2">
              {sessionItems.map((item, idx) => (
                <li
                  key={item}
                  className={`rounded-xl border px-3 py-2 text-sm ${
                    idx === 0
                      ? "border-cyan-300/60 bg-cyan-300/10 text-cyan-100"
                      : "border-slate-700 bg-slate-800/50 text-slate-200"
                  }`}
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <main className="flex min-h-[calc(100vh-2.5rem)] flex-col rounded-3xl border border-slate-200 bg-white/70 p-4 shadow-[0_18px_40px_rgba(14,44,68,0.13)] backdrop-blur lg:p-5">
          <header className="rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-bold text-slate-100">Conversation Workspace</h2>
              </div>
              <div className="flex items-center gap-2 rounded-full border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700">
                <span className="h-2 w-2 rounded-full bg-emerald-400" />
                Multi-Agent Reasoning Active
              </div>
            </div>
          </header>

          <section className="mt-4 flex-1 space-y-4 overflow-y-auto pr-1">
            {messages.map((message, messageIndex) => {
              if (message.role === "user") {
                return (
                  <article key={message.id} className="flex justify-end">
                    <div className="max-w-[85%] animate-fade-up space-y-3 rounded-2xl rounded-br-md bg-slate-900 p-4 text-slate-100 shadow">
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs uppercase tracking-[0.16em] text-cyan-300">User Query</p>
                        <p className="text-sm text-slate-300">{messageTime(message.createdAt)}</p>
                      </div>
                      <p className="text-base font-medium leading-relaxed text-slate-100">{message.text}</p>
                    </div>
                  </article>
                );
              }
              const responseIsFailure = message.response ? isFailureResponse(message.response) : false;

              return (
                <article key={message.id} className="animate-fade-up space-y-3 rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-[0.16em] text-cyan-700">Agent Response</p>
                      <p className="text-sm text-slate-600">{messageTime(message.createdAt)}</p>
                    </div>
                    {message.response && !responseIsFailure ? (
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                          message.response.confidence === "high"
                            ? "bg-emerald-100 text-emerald-800"
                            : message.response.confidence === "medium"
                              ? "bg-amber-100 text-amber-800"
                              : "bg-rose-100 text-rose-800"
                        }`}
                      >
                        {message.response.confidence} confidence
                      </span>
                    ) : null}
                  </div>

                  {message.text ? <p className="text-base font-medium leading-relaxed text-slate-950">{message.text}</p> : null}

                  {message.isStreaming ? (
                    <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-3">
                      <div className="flex items-center gap-3">
                        <div className="signal-spinner" aria-hidden="true">
                          <span className="signal-spinner__ring signal-spinner__ring-a" />
                          <span className="signal-spinner__ring signal-spinner__ring-b" />
                          <span className="signal-spinner__core" />
                        </div>
                        <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-cyan-900">Running your analysis</p>
                          <span className="animate-fade-up rounded-full bg-white px-2 py-1 text-sm font-medium text-cyan-800">
                            {(message.statusUpdates ?? []).at(-1) ?? "Initializing pipeline..."}
                          </span>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {message.response ? (
                    responseIsFailure ? (
                      <>
                        <section className="rounded-xl border border-rose-200 bg-rose-50 p-3">
                          <p className="text-xs uppercase tracking-wide text-rose-700">Request Failed</p>
                          <p className="mt-1.5 text-sm text-rose-900">
                            No governed result payload was returned. Review the trace for failure details.
                          </p>
                        </section>
                        <AnalysisTrace steps={message.response.trace} />
                      </>
                    ) : (
                      <>
                        <section className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                          <p className="text-xs uppercase tracking-wide text-slate-500">Why It Matters</p>
                          <p className="mt-1.5 text-sm text-slate-700">{message.response.whyItMatters}</p>
                        </section>

                        {(() => {
                          const userQuery =
                            [...messages.slice(0, messageIndex)].reverse().find((entry) => entry.role === "user")?.text ?? "";
                          const metricPeriodLabel = deriveMetricPeriodLabel(message.response, userQuery, message.createdAt);
                          const rowsRetrieved = rowsRetrievedCount(message.response);
                          const runtime = formatRuntime(message.requestDurationMs, message.isStreaming);
                          return (
                            <>
                              <section className="rounded-xl border border-slate-200 bg-slate-50 p-2.5">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">{metricPeriodLabel}</span>
                                  <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                                    Rows: {integerFormatter.format(rowsRetrieved)}
                                  </span>
                                  <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">Runtime: {runtime}</span>
                                </div>
                              </section>

                              <section className="grid gap-3 sm:grid-cols-3">
                                {summaryCardsForResponse(message.response).map((card, index) => (
                                  <div key={`${card.label}-${index}`} className="rounded-xl border border-slate-200 bg-white p-3">
                                    <p className="text-xs uppercase tracking-wide text-slate-500">{card.label}</p>
                                    <p className="mt-2 text-xl font-bold text-slate-900">{card.value}</p>
                                    {card.detail ? <p className="mt-1 text-sm text-slate-700">{card.detail}</p> : null}
                                  </div>
                                ))}
                              </section>
                            </>
                          );
                        })()}

                        <EvidenceTable
                          rows={message.response.evidence}
                          artifacts={message.response.artifacts}
                          primaryVisual={message.response.primaryVisual}
                          analysisType={message.response.analysisType}
                          dataTables={message.response.dataTables}
                        />
                        <DataExplorer tables={buildRenderableTables(message.response)} />

                        <section className="rounded-2xl border border-slate-200 bg-white/85 p-4">
                          <h3 className="text-sm font-semibold tracking-wide text-slate-900">Priority Insights</h3>
                          <div className="mt-3 grid gap-2 md:grid-cols-3">
                            {[...message.response.insights]
                              .sort((a, b) => insightImportanceRank[a.importance] - insightImportanceRank[b.importance])
                              .slice(0, 3)
                              .map((insight) => (
                              <article key={insight.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                                <p
                                  className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                                    insight.importance === "high"
                                      ? "bg-rose-100 text-rose-700"
                                      : "bg-amber-100 text-amber-800"
                                  }`}
                                >
                                  {insight.importance} importance
                                </p>
                                <p className="mt-2 text-sm font-semibold text-slate-900">{insight.title}</p>
                                <p className="mt-1 text-sm leading-relaxed text-slate-700">{insight.detail}</p>
                              </article>
                              ))}
                          </div>
                        </section>

                        <AnalysisTrace steps={message.response.trace} />

                        <section className="grid gap-3 md:grid-cols-2">
                          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                            <p className="text-xs uppercase tracking-wide text-slate-500">Assumptions</p>
                            <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-relaxed text-slate-700 marker:text-slate-400">
                              {message.response.assumptions.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                            <p className="text-xs uppercase tracking-wide text-slate-500">Suggested Next Questions</p>
                            <div className="mt-2 flex flex-wrap gap-2">
                              {message.response.suggestedQuestions.map((question) => (
                                <button
                                  key={question}
                                  onClick={() => setInput(question)}
                                  className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-left text-xs font-medium text-slate-700 transition hover:border-cyan-500 hover:text-cyan-800"
                                  type="button"
                                >
                                  {question}
                                </button>
                              ))}
                            </div>
                          </div>
                        </section>
                      </>
                    )
                  ) : null}
                </article>
              );
            })}

          </section>

          <footer className="mt-4 rounded-2xl border border-slate-200 bg-white/85 p-3">
            {showStarterPrompts ? (
              <div className="mb-2 flex flex-wrap gap-2">
                {starterPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => setInput(prompt)}
                    className="rounded-full border border-slate-300 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700 transition hover:border-cyan-500 hover:text-cyan-900"
                    type="button"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            ) : null}

            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submitQuery(input);
              }}
              className="flex flex-col gap-2 sm:flex-row"
            >
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                rows={2}
                placeholder="Ask a Customer Insights Analyst a question..."
                className="min-h-[74px] flex-1 resize-none rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-inner outline-none ring-cyan-500 placeholder:text-slate-400 focus:ring-2"
              />
              <button
                disabled={isLoading || !input.trim()}
                className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
                type="submit"
              >
                {isLoading ? "Analyzing..." : "Send"}
              </button>
            </form>
          </footer>
        </main>

        <aside className="rounded-3xl border border-slate-200 bg-white/80 p-4 shadow-[0_14px_32px_rgba(14,44,68,0.1)] backdrop-blur">
          <div className="rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3">
            <p className="text-xl font-bold text-slate-100">Snapshot</p>
            <p className="mt-1 text-sm text-slate-300">
              {latestResponseIsFailure
                ? "Latest request failed. Open the trace for diagnostics."
                : "Review top signals, confidence context, and suggested next actions."}
            </p>
          </div>

          {latestResponse ? (
            latestResponseIsFailure ? (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
                The latest run did not return a governed result. Inspect the analysis trace in the conversation panel.
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Top Signal</p>
                  <p className="mt-1 text-sm font-semibold text-slate-900">{latestResponse.insights[0]?.title ?? "No insight yet"}</p>
                  <p className="mt-1 text-sm leading-relaxed text-slate-700">
                    {latestResponse.insights[0]?.detail ?? "Run an analysis to populate signal context."}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Confidence Basis</p>
                  <p className="mt-1 text-sm font-semibold text-slate-900">{toTitleCase(latestResponse.confidence)} confidence</p>
                  {latestResponse.confidenceReason?.trim() ? (
                    <p className="mt-1 text-sm leading-relaxed text-slate-700">{latestResponse.confidenceReason.trim()}</p>
                  ) : null}
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Next Action</p>
                  <p className="mt-1 text-sm leading-relaxed text-slate-700">{latestNextAction}</p>
                </div>
              </div>
            )
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
              Ask a question to populate a real-time decision brief.
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
