"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnalysisTrace } from "@/components/analysis-trace";
import { DataExplorer } from "@/components/data-explorer";
import { EvidenceTable } from "@/components/evidence-table";
import { readNdjsonStream } from "@/lib/stream";
import type { AgentResponse, ChatMessage, ChatStreamEvent, DataTable, MetricPoint, SummaryCard } from "@/lib/types";

type StarterPrompt = {
  question: string;
  tag: string;
};

const starterPrompts: StarterPrompt[] = [
  { question: "Show me total sales last month.", tag: "Quick Metric" },
  { question: "Show me sales by state in descending order.", tag: "Ranking" },
  { question: "Show me new vs repeat customers by month for the last 6 months.", tag: "Retention Trend" },
  {
    question: "What were my sales, transactions, and average sale amount for Q4 2025 compared to the same period last year?",
    tag: "YoY Snapshot",
  },
  {
    question:
      "For the last 8 weeks, which day of week and transaction time window drive the highest average ticket and transaction volume?",
    tag: "Purchase Patterns",
  },
  {
    question:
      "What were my top and bottom performing stores for 2025, what was the new vs repeat customer mix for each one, and how does that compare to the prior period?",
    tag: "Store Comparison",
  },
];

const sessionItems = [
  "Demo",
  "Q4 YoY Performance",
  "Store Performance Monitor",
  "Channel Mix Deep Dive",
];

function createWelcomeMessage(): ChatMessage {
  return {
    id: "assistant-welcome",
    role: "assistant",
    text: "Ask any Customer Insights question across Sales, Loyalty, Demographics, Geographics, or Industry. I will return key insights, exportable data, and an audited trace.",
    createdAt: new Date().toISOString(),
  };
}

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

function isRowsRetrievedLabel(label: string): boolean {
  return normalizeMetricLabel(label).toLowerCase() === "rows retrieved";
}

function resolveMetricUnit(metric: KpiMetric): MetricPoint["unit"] {
  return metric.unit;
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

function splitSummaryCardLabel(label: string): { title: string; qualifier: string } {
  const trimmed = label.trim();
  const match = trimmed.match(/^(.*?)(?:\s*\(([^)]+)\))$/);
  if (!match) {
    return { title: trimmed, qualifier: "" };
  }

  return {
    title: match[1].trim(),
    qualifier: match[2].trim(),
  };
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

function isMonthlyPeriodContext(response: AgentResponse, userQuery: string): boolean {
  const chartX = response.chartConfig?.x?.toLowerCase() ?? "";
  const chartXLabel = response.chartConfig?.xLabel?.toLowerCase() ?? "";
  if (chartX.includes("month") || chartXLabel.includes("month")) return true;

  const hasMonthColumn = (response.dataTables ?? []).some((table) =>
    table.columns.some((column) => column.toLowerCase().includes("month")),
  );
  if (hasMonthColumn) return true;

  return /\b(by month|per month|monthly|last\s+\d+\s+months?)\b/i.test(userQuery);
}

function adjustInclusiveMonthlyEnd(start: Date, end: Date, isMonthlyContext: boolean): Date {
  if (!isMonthlyContext) return end;
  if (end.getDate() !== 1) return end;
  if (end.getTime() < start.getTime()) return end;
  return new Date(end.getFullYear(), end.getMonth() + 1, 0);
}

function deriveMetricPeriodLabel(response: AgentResponse, userQuery: string, responseCreatedAt: string): string {
  const explicitLabel = (response.periodLabel ?? "").trim();
  if (explicitLabel) return explicitLabel;

  const explicitStart = parseDateValue(response.periodStart ?? "");
  const explicitEnd = parseDateValue(response.periodEnd ?? "");
  if (explicitStart && explicitEnd) {
    const adjustedEnd = adjustInclusiveMonthlyEnd(explicitStart, explicitEnd, isMonthlyPeriodContext(response, userQuery));
    return formatDateRange(explicitStart, adjustedEnd);
  }

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

type EnvironmentLabel = "Sandbox" | "Production";

interface AgentWorkspaceProps {
  initialEnvironment: EnvironmentLabel;
}

type ResponseFeedback = "up" | "down";

function isEnvironmentLabel(value: unknown): value is EnvironmentLabel {
  return value === "Sandbox" || value === "Production";
}

export function AgentWorkspace({ initialEnvironment }: AgentWorkspaceProps) {
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [areStarterPromptsExpanded, setAreStarterPromptsExpanded] = useState(true);
  const [environment, setEnvironment] = useState<EnvironmentLabel>(initialEnvironment);
  const [isLeftPaneVisible, setIsLeftPaneVisible] = useState(true);
  const [isRightPaneVisible, setIsRightPaneVisible] = useState(true);
  const [feedbackByMessageId, setFeedbackByMessageId] = useState<Record<string, ResponseFeedback | undefined>>({});
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>(() => [createWelcomeMessage()]);
  const inFlightRequestRef = useRef<{
    controller: AbortController;
    assistantMessageId: string;
    requestStartedAtMs: number;
  } | null>(null);

  const latestResponseMessage = useMemo(
    () => [...messages].reverse().find((message) => message.role === "assistant" && message.response),
    [messages],
  );
  const latestResponse = latestResponseMessage?.response;
  const latestResponseIsFailure = useMemo(
    () => (latestResponse ? isFailureResponse(latestResponse) : false),
    [latestResponse],
  );
  const latestNextAction = useMemo(() => nextActionBody(latestResponse?.suggestedQuestions), [latestResponse]);
  const latestSnapshotMetadata = useMemo(() => {
    if (!latestResponseMessage?.response) return null;
    if (isFailureResponse(latestResponseMessage.response)) return null;

    const assistantIndex = messages.findIndex((entry) => entry.id === latestResponseMessage.id);
    const userQuery =
      assistantIndex >= 0
        ? [...messages.slice(0, assistantIndex)].reverse().find((entry) => entry.role === "user")?.text ?? ""
        : "";
    const periodLabel = deriveMetricPeriodLabel(latestResponseMessage.response, userQuery, latestResponseMessage.createdAt);
    const rowsRetrieved = rowsRetrievedCount(latestResponseMessage.response);
    const runtime = formatRuntime(latestResponseMessage.requestDurationMs, latestResponseMessage.isStreaming);

    return {
      periodLabel,
      rowsLabel: `Rows: ${integerFormatter.format(rowsRetrieved)}`,
      runtimeLabel: `Runtime: ${runtime}`,
    };
  }, [messages, latestResponseMessage]);
  const latestSnapshotMetadataDisplay = useMemo(() => {
    if (!latestResponse || latestResponseIsFailure) return null;
    if (latestSnapshotMetadata) return latestSnapshotMetadata;

    const fallbackDate = parseDateValue(latestResponseMessage?.createdAt ?? "");
    const periodLabel = fallbackDate ? `As of ${dateFormatter.format(fallbackDate)}` : `As of ${dateFormatter.format(new Date())}`;
    return {
      periodLabel,
      rowsLabel: `Rows: ${integerFormatter.format(rowsRetrievedCount(latestResponse))}`,
      runtimeLabel: `Runtime: ${formatRuntime(latestResponseMessage?.requestDurationMs, latestResponseMessage?.isStreaming)}`,
    };
  }, [latestResponse, latestResponseIsFailure, latestSnapshotMetadata, latestResponseMessage]);
  const showStarterPrompts = useMemo(() => !messages.some((message) => message.role === "user"), [messages]);
  const hasOddStarterCount = starterPrompts.length % 2 === 1;
  const workspaceGridClassName = useMemo(() => {
    if (isLeftPaneVisible && isRightPaneVisible) {
      return "mx-auto grid w-full max-w-[1680px] grid-cols-1 gap-5 px-4 py-5 lg:h-screen lg:grid-cols-[260px_minmax(0,1fr)_320px] lg:items-start lg:px-6 lg:py-6";
    }
    if (isLeftPaneVisible) {
      return "mx-auto grid w-full max-w-[1680px] grid-cols-1 gap-5 px-4 py-5 lg:h-screen lg:grid-cols-[260px_minmax(0,1fr)] lg:items-start lg:px-6 lg:py-6";
    }
    if (isRightPaneVisible) {
      return "mx-auto grid w-full max-w-[1680px] grid-cols-1 gap-5 px-4 py-5 lg:h-screen lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start lg:px-6 lg:py-6";
    }
    return "mx-auto grid w-full max-w-[1680px] grid-cols-1 gap-5 px-4 py-5 lg:h-screen lg:grid-cols-1 lg:items-start lg:px-6 lg:py-6";
  }, [isLeftPaneVisible, isRightPaneVisible]);

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

  useEffect(() => {
    return () => {
      inFlightRequestRef.current?.controller.abort();
      inFlightRequestRef.current = null;
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

  const setResponseFeedback = (messageId: string, next: ResponseFeedback): void => {
    setFeedbackByMessageId((prev) => {
      const current = prev[messageId];
      return {
        ...prev,
        [messageId]: current === next ? undefined : next,
      };
    });
  };

  const stopCurrentRequest = (): void => {
    const inFlight = inFlightRequestRef.current;
    if (!inFlight) return;

    inFlight.controller.abort();
    updateAssistantMessage(inFlight.assistantMessageId, (draft) => {
      if (!draft.isStreaming) return draft;
      const statusUpdates = draft.statusUpdates ?? [];
      const finalStatusUpdates = statusUpdates.at(-1) === "Stopped" ? statusUpdates : [...statusUpdates, "Stopped"];
      return {
        ...draft,
        text: draft.text || "Analysis stopped.",
        isStreaming: false,
        statusUpdates: finalStatusUpdates,
        requestDurationMs:
          draft.requestDurationMs ?? Math.max(1, Math.round(performance.now() - inFlight.requestStartedAtMs)),
      };
    });
    setIsLoading(false);
    inFlightRequestRef.current = null;
  };

  const composeNewThread = (): void => {
    stopCurrentRequest();
    setSessionId(crypto.randomUUID());
    setInput("");
    setAreStarterPromptsExpanded(true);
    setFeedbackByMessageId({});
    setMessages([createWelcomeMessage()]);
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
      const controller = new AbortController();
      inFlightRequestRef.current = {
        controller,
        assistantMessageId,
        requestStartedAtMs,
      };
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, message: clean }),
        signal: controller.signal,
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
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      const failureText =
        error instanceof Error && error.message.trim()
          ? error.message.trim()
          : "Request failed.";
      updateAssistantMessage(assistantMessageId, (draft) => ({
        ...draft,
        text: failureText,
        isStreaming: false,
        statusUpdates: [...(draft.statusUpdates ?? []), "Request failed"],
        requestDurationMs: Math.max(1, Math.round(performance.now() - requestStartedAtMs)),
      }));
    } finally {
      if (inFlightRequestRef.current?.assistantMessageId === assistantMessageId) {
        inFlightRequestRef.current = null;
      }
      setIsLoading(false);
    }
  }

  const composerFooter = (
    <footer className="mt-4 rounded-[1.75rem] border border-slate-300/80 bg-[linear-gradient(145deg,rgba(255,255,255,0.96),rgba(242,248,253,0.92))] p-3 shadow-[0_14px_30px_rgba(14,44,68,0.08)] sm:p-4">
      {showStarterPrompts ? (
        <div className="mb-3 rounded-2xl border border-slate-200/90 bg-white/85 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">Starter Questions</p>
              <p className="mt-1 text-sm text-slate-700">Start with a baseline or jump into a deeper diagnostic path.</p>
            </div>
            <button
              type="button"
              onClick={() => setAreStarterPromptsExpanded((prev) => !prev)}
              aria-expanded={areStarterPromptsExpanded}
              aria-controls="starter-questions-grid"
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 transition hover:border-cyan-500 hover:text-cyan-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/50"
            >
              <span>{areStarterPromptsExpanded ? "Collapse" : "Expand"}</span>
              <svg
                viewBox="0 0 20 20"
                aria-hidden="true"
                className={`h-4 w-4 transition-transform ${areStarterPromptsExpanded ? "rotate-0" : "-rotate-90"}`}
              >
                <path d="M5.25 7.5L10 12.25L14.75 7.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          {areStarterPromptsExpanded ? (
            <div id="starter-questions-grid" className="mt-3 grid gap-2 sm:grid-cols-2">
              {starterPrompts.map((prompt, index) => {
                const isLastOddCard = hasOddStarterCount && index === starterPrompts.length - 1;
                return (
                  <button
                    key={prompt.question}
                    onClick={() => setInput(prompt.question)}
                    className={`group relative flex animate-fade-up flex-col items-start justify-start rounded-2xl border border-slate-300/90 bg-[linear-gradient(160deg,#fefefe,#edf4fb)] px-3 py-2.5 text-left text-slate-900 shadow-[0_8px_18px_rgba(14,44,68,0.08)] transition duration-200 hover:-translate-y-0.5 hover:border-cyan-500 hover:shadow-[0_14px_24px_rgba(14,44,68,0.14)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/50 active:translate-y-0 ${
                      isLastOddCard ? "sm:col-span-2" : ""
                    }`}
                    style={{ animationDelay: `${index * 40}ms` }}
                    type="button"
                  >
                    <span className="rounded-full bg-white px-2 py-[2px] text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-600">
                      {prompt.tag}
                    </span>
                    <span className="absolute right-3 top-3 w-6 text-right text-xs font-semibold tabular-nums text-slate-500 group-hover:text-cyan-800">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <p className="mt-1.5 font-[var(--font-body)] text-sm font-medium leading-tight text-slate-800">{prompt.question}</p>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submitQuery(input);
        }}
        className="flex flex-col gap-2.5 sm:flex-row"
      >
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={1}
          placeholder="Ask a Customer Insights Analyst a question..."
          className="min-h-[63px] flex-1 resize-none rounded-2xl border border-slate-300 bg-[linear-gradient(180deg,#ffffff,#f6faff)] px-3.5 py-2.5 text-sm font-medium text-slate-900 shadow-[inset_0_1px_2px_rgba(15,23,42,0.06)] outline-none ring-cyan-500 placeholder:font-normal placeholder:text-slate-500 focus:ring-2"
        />
        <button
          aria-label={isLoading ? "Stop analysis" : "Send message"}
          disabled={!isLoading && !input.trim()}
          className={`min-h-[42px] rounded-2xl border px-6 py-2.5 text-sm font-semibold text-white shadow-[0_10px_18px_rgba(15,36,56,0.24)] transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:border-slate-400 disabled:bg-slate-400 ${
            isLoading
              ? "border-rose-700 bg-[linear-gradient(145deg,#7f1d1d,#b91c1c)] hover:bg-[linear-gradient(145deg,#991b1b,#dc2626)]"
              : "border-slate-700 bg-slate-900 hover:bg-slate-800"
          }`}
          onClick={isLoading ? stopCurrentRequest : undefined}
          type={isLoading ? "button" : "submit"}
        >
          {isLoading ? "Stop" : "Send"}
        </button>
      </form>
    </footer>
  );

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[radial-gradient(circle_at_10%_10%,#d7f5ff_0,#f5f2e9_38%,#eff4f8_100%)] lg:h-screen lg:overflow-hidden">
      <div className="pointer-events-none absolute -left-24 top-12 h-80 w-80 rounded-full bg-cyan-300/40 blur-3xl" />
      <div className="pointer-events-none absolute right-10 top-36 h-72 w-72 rounded-full bg-orange-200/50 blur-3xl" />

      <div className={workspaceGridClassName}>
        {isLeftPaneVisible ? (
          <aside className="rounded-3xl border border-slate-200 bg-slate-900 p-4 text-slate-100 shadow-[0_20px_50px_rgba(15,23,42,0.3)] lg:h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto">
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
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs uppercase tracking-wide text-slate-400">Sessions</p>
              <button
                type="button"
                onClick={composeNewThread}
                aria-label="Compose new thread"
                title="Compose new thread"
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-400/40 bg-cyan-400/10 text-cyan-100 transition hover:border-cyan-300 hover:bg-cyan-400/20 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50"
              >
                <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4">
                  <path
                    d="M13.97 3.47a1.75 1.75 0 0 1 2.47 2.47l-8.2 8.2-3.24.77.77-3.24 8.2-8.2Z"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M11.9 5.55l2.55 2.55"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
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
        ) : null}

        <section className="relative flex min-h-[calc(100vh-2.5rem)] flex-col lg:h-[calc(100vh-3rem)] lg:min-h-0">
          <header className="relative z-10 rounded-2xl border border-slate-700/90 bg-slate-900 px-5 py-3 shadow-[0_22px_44px_rgba(15,23,42,0.26)]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-bold text-slate-100">Conversation Workspace</h2>
              </div>
              <div
                className="inline-flex items-center gap-1 rounded-xl border border-slate-700/90 bg-slate-800/80 p-1"
                role="group"
                aria-label="Pane selector"
              >
                <button
                  type="button"
                  onClick={() => setIsLeftPaneVisible((prev) => !prev)}
                  aria-pressed={isLeftPaneVisible}
                  aria-label={isLeftPaneVisible ? "Hide left pane" : "Show left pane"}
                  title={isLeftPaneVisible ? "Hide left pane" : "Show left pane"}
                  className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border transition ${
                    isLeftPaneVisible
                      ? "border-cyan-400/70 bg-cyan-500/18 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(103,232,249,0.18)] hover:bg-cyan-500/26"
                      : "border-slate-600/80 bg-slate-800/70 text-slate-300 hover:border-slate-500 hover:bg-slate-700/80 hover:text-slate-100"
                  }`}
                >
                  <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4">
                    <rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2.25" fill="none" stroke="currentColor" strokeWidth="1.4" />
                    <rect x="4.4" y="5.3" width="3.2" height="9.4" rx="0.9" fill="currentColor" opacity="0.85" />
                    <path
                      d="M11.8 7.2 9.5 10l2.3 2.8"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                <button
                  type="button"
                  onClick={() => setIsRightPaneVisible((prev) => !prev)}
                  aria-pressed={isRightPaneVisible}
                  aria-label={isRightPaneVisible ? "Hide right pane" : "Show right pane"}
                  title={isRightPaneVisible ? "Hide right pane" : "Show right pane"}
                  className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border transition ${
                    isRightPaneVisible
                      ? "border-cyan-400/70 bg-cyan-500/18 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(103,232,249,0.18)] hover:bg-cyan-500/26"
                      : "border-slate-600/80 bg-slate-800/70 text-slate-300 hover:border-slate-500 hover:bg-slate-700/80 hover:text-slate-100"
                  }`}
                >
                  <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4">
                    <rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2.25" fill="none" stroke="currentColor" strokeWidth="1.4" />
                    <rect x="12.4" y="5.3" width="3.2" height="9.4" rx="0.9" fill="currentColor" opacity="0.85" />
                    <path
                      d="M8.2 7.2 10.5 10l-2.3 2.8"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              </div>
            </div>
          </header>

          <div className="relative mt-3 flex min-h-0 flex-1 flex-col rounded-[2rem] border border-slate-200/90 bg-[linear-gradient(180deg,rgba(255,255,255,0.82),rgba(241,247,251,0.94))] p-4 pt-5 shadow-[0_18px_40px_rgba(14,44,68,0.13)] backdrop-blur lg:overflow-hidden lg:p-5 lg:pt-6">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 z-10 h-8 bg-[linear-gradient(180deg,rgba(243,247,251,0.92)_0%,rgba(243,247,251,0.72)_38%,rgba(243,247,251,0.28)_68%,rgba(243,247,251,0)_100%)]"
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-8 bg-[linear-gradient(0deg,rgba(243,247,251,0.92)_0%,rgba(243,247,251,0.72)_38%,rgba(243,247,251,0.28)_68%,rgba(243,247,251,0)_100%)]"
            />
            <section className="flex min-h-0 flex-1 flex-col overflow-y-auto pt-1 pr-1">
              <div className="space-y-4">
                {messages.map((message, messageIndex) => {
              if (message.role === "user") {
                return (
                  <article key={message.id} className="flex justify-end">
                    <div className="max-w-[85%] animate-fade-up space-y-3 rounded-2xl rounded-br-md bg-slate-900 p-4 text-slate-100 shadow">
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs uppercase tracking-[0.16em] text-cyan-300">User Query</p>
                        <p className="text-sm text-slate-300">{messageTime(message.createdAt)}</p>
                      </div>
                      <p className="text-sm font-medium leading-relaxed text-slate-100">{message.text}</p>
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

                  {message.text ? <p className="text-sm font-medium leading-relaxed text-slate-950">{message.text}</p> : null}

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
                            No result payload was returned. Review the trace for failure details.
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

                        <section className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                          <div className="grid gap-3 sm:grid-cols-3">
                            {summaryCardsForResponse(message.response).map((card, index) => {
                              const { title, qualifier } = splitSummaryCardLabel(card.label);

                              return (
                                <div
                                  key={`${card.label}-${index}`}
                                  className="flex min-h-[7.5rem] flex-col rounded-xl border border-slate-200 bg-white px-3 py-3"
                                >
                                  <div className="min-h-[2.5rem]">
                                    <p className="text-[11px] uppercase tracking-wide text-slate-500">{title}</p>
                                    {qualifier ? (
                                      <p className="mt-0.5 text-[11px] uppercase tracking-wide text-slate-500">{qualifier}</p>
                                    ) : null}
                                  </div>
                                  <p className="mt-1 text-[1.35rem] font-bold tabular-nums leading-none text-slate-900">{card.value}</p>
                                  <div className="mt-auto min-h-[1.5rem] pt-1">
                                    {card.detail ? <p className="text-sm leading-snug text-slate-700">{card.detail}</p> : null}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </section>

                        <EvidenceTable
                          chartConfig={message.response.chartConfig}
                          tableConfig={message.response.tableConfig}
                          primaryVisual={message.response.primaryVisual}
                          dataTables={message.response.dataTables}
                          comparisons={message.response.comparisons}
                        />

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
                        <DataExplorer tables={buildRenderableTables(message.response)} />

                        <AnalysisTrace steps={message.response.trace} />

                        <section className={`grid gap-3 ${(message.response.assumptions ?? []).length > 0 ? "md:grid-cols-2" : ""}`}>
                          {(message.response.assumptions ?? []).length > 0 ? (
                            <div className="rounded-xl border border-slate-200 bg-[linear-gradient(180deg,rgba(248,251,255,0.95),rgba(241,246,252,0.92))] p-3">
                              <p className="text-xs uppercase tracking-wide text-slate-500">Assumptions</p>
                              <p className="mt-1 text-xs text-slate-600">Interpretation constraints used for this answer.</p>
                              <ol className="mt-2 space-y-2">
                                {message.response.assumptions.map((item, index) => (
                                  <li
                                    key={item}
                                    className="flex items-start gap-2.5 rounded-lg border border-slate-200/80 bg-white/90 px-2.5 py-2 text-sm leading-relaxed text-slate-700 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.5)]"
                                  >
                                    <span className="mt-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-100 px-1 text-[11px] font-semibold text-slate-700">
                                      {index + 1}
                                    </span>
                                    <span className="flex-1">{item}</span>
                                  </li>
                                ))}
                              </ol>
                            </div>
                          ) : null}
                          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                            <p className="text-xs uppercase tracking-wide text-slate-500">Suggested Next Questions</p>
                            <p className="mt-1 text-xs text-slate-600">Pick one to auto-fill the composer.</p>
                            <div className="mt-2 space-y-2">
                              {message.response.suggestedQuestions.map((question, index) => (
                                <button
                                  key={question}
                                  onClick={() => setInput(question)}
                                  className="group flex w-full items-start gap-3 rounded-xl border border-slate-300/90 bg-white px-3 py-2.5 text-left transition hover:-translate-y-0.5 hover:border-cyan-500 hover:shadow-[0_10px_20px_rgba(14,44,68,0.10)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/50 active:translate-y-0"
                                  type="button"
                                >
                                  <span className="mt-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-100 px-1 text-[11px] font-semibold text-slate-700 group-hover:bg-cyan-100 group-hover:text-cyan-800">
                                    {index + 1}
                                  </span>
                                  <span className="flex-1 text-sm font-medium leading-relaxed text-slate-800 group-hover:text-slate-900">
                                    {question}
                                  </span>
                                  <span className="pt-0.5 text-sm text-slate-400 group-hover:text-cyan-700" aria-hidden="true">
                                    →
                                  </span>
                                </button>
                              ))}
                            </div>
                          </div>
                        </section>
                      </>
                    )
                  ) : null}

                  {message.response && !responseIsFailure && !message.isStreaming ? (
                    <footer className="mt-2 flex items-center justify-end border-t border-slate-200 pt-3">
                      <div className="inline-flex items-center gap-2">
                        <button
                          type="button"
                          aria-label="Thumbs up"
                          aria-pressed={feedbackByMessageId[message.id] === "up"}
                          title="Thumbs up"
                          onClick={() => setResponseFeedback(message.id, "up")}
                          className={`inline-flex h-8 w-8 items-center justify-center rounded-full border transition ${
                            feedbackByMessageId[message.id] === "up"
                              ? "border-emerald-500 bg-emerald-100 text-emerald-800"
                              : "border-slate-300 bg-white text-slate-600 hover:border-emerald-400 hover:text-emerald-700"
                          }`}
                        >
                          <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4">
                            <path
                              d="M8.75 3.5A1.75 1.75 0 0 1 10.5 5.25v2.1h4.36a1.75 1.75 0 0 1 1.71 2.13l-1.2 5.3a1.75 1.75 0 0 1-1.71 1.37H8.5a1.75 1.75 0 0 1-1.75-1.75V8.33c0-.39.13-.76.37-1.06l1.2-1.5A1.75 1.75 0 0 0 8.75 4.67V3.5ZM4.5 8.75a1 1 0 0 1 1 1V15a1 1 0 0 1-1 1h-.25a1 1 0 0 1-1-1V9.75a1 1 0 0 1 1-1h.25Z"
                              fill="currentColor"
                            />
                          </svg>
                        </button>
                        <button
                          type="button"
                          aria-label="Thumbs down"
                          aria-pressed={feedbackByMessageId[message.id] === "down"}
                          title="Thumbs down"
                          onClick={() => setResponseFeedback(message.id, "down")}
                          className={`inline-flex h-8 w-8 items-center justify-center rounded-full border transition ${
                            feedbackByMessageId[message.id] === "down"
                              ? "border-rose-500 bg-rose-100 text-rose-800"
                              : "border-slate-300 bg-white text-slate-600 hover:border-rose-400 hover:text-rose-700"
                          }`}
                        >
                          <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4">
                            <path
                              d="M11.25 16.5a1.75 1.75 0 0 1-1.75-1.75v-2.1H5.14a1.75 1.75 0 0 1-1.71-2.13l1.2-5.3A1.75 1.75 0 0 1 6.34 3.85H11.5a1.75 1.75 0 0 1 1.75 1.75v6.07c0 .39-.13.76-.37 1.06l-1.2 1.5a1.75 1.75 0 0 0-.43 1.1v1.17ZM15.5 11.25a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h.25a1 1 0 0 1 1 1v5.25a1 1 0 0 1-1 1h-.25Z"
                              fill="currentColor"
                            />
                          </svg>
                        </button>
                      </div>
                    </footer>
                  ) : null}
                </article>
              );
                })}
              </div>
              <div className="sticky bottom-0 z-20 mt-auto shrink-0 pt-4">{composerFooter}</div>
            </section>
          </div>
        </section>

        {isRightPaneVisible ? (
          <aside className="rounded-3xl border border-slate-200 bg-white/80 p-4 shadow-[0_14px_32px_rgba(14,44,68,0.1)] backdrop-blur lg:h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto">
          <div className="rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3">
            <p className="text-xl font-bold text-slate-100">Current Snapshot</p>
            <p className="mt-1 text-sm text-slate-300">
              Review top signals, confidence context, and suggested next actions for your latest query.
            </p>
          </div>

          {latestResponse ? (
            latestResponseIsFailure ? (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
                The latest run did not return a result. Inspect the analysis trace in the conversation panel.
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
                {latestSnapshotMetadataDisplay ? (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                        {latestSnapshotMetadataDisplay.periodLabel}
                      </span>
                      <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                        {latestSnapshotMetadataDisplay.rowsLabel}
                      </span>
                      <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                        {latestSnapshotMetadataDisplay.runtimeLabel}
                      </span>
                    </div>
                  </div>
                ) : null}
              </div>
            )
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
              Ask a question to populate a real-time decision brief.
            </div>
          )}
          </aside>
        ) : null}
      </div>
    </div>
  );
}
