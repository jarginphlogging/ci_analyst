"use client";

import { useState } from "react";
import type { TraceStep } from "@/lib/types";

const statusClass: Record<TraceStep["status"], string> = {
  done: "bg-emerald-100 text-emerald-800 border-emerald-200",
  running: "bg-amber-100 text-amber-800 border-amber-200",
  blocked: "bg-rose-100 text-rose-800 border-rose-200",
};

function renderPayload(payload: Record<string, unknown> | undefined): string {
  if (!payload) return "{}";
  try {
    const sanitized = { ...payload };
    delete sanitized.llmPrompts;
    delete sanitized.llmResponses;
    return JSON.stringify(sanitized, null, 2);
  } catch {
    return "{\n  \"error\": \"unable to render payload\"\n}";
  }
}

interface LlmPromptEntry {
  provider?: string;
  metadata?: Record<string, unknown>;
  systemPrompt?: string;
  userPrompt?: string;
  maxTokens?: number | null;
  temperature?: number | null;
}

interface LlmResponseEntry {
  provider?: string;
  metadata?: Record<string, unknown>;
  humanResponse?: string | null;
  rawResponse?: string | null;
  parsedResponse?: Record<string, unknown> | null;
  error?: string | null;
}

interface PromptSection {
  label: string;
  content: string;
}

interface SqlPlanStepMeta {
  id: string;
  goal?: string;
}

interface LlmExchange {
  index: number;
  prompt?: LlmPromptEntry;
  response?: LlmResponseEntry;
  stepId?: string;
  stepGoal?: string;
}

interface SqlExchangeGroup {
  key: string;
  title: string;
  goal?: string;
  exchanges: LlmExchange[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function providerBadgeLabel(entry?: LlmPromptEntry | LlmResponseEntry): string {
  const provider = String(entry?.provider ?? "").trim().toLowerCase();
  const metadata = asRecord(entry?.metadata);
  if (provider === "analyst") {
    const analystTarget = String(metadata?.analystTarget ?? "").trim().toLowerCase();
    const providerMode = String(metadata?.providerMode ?? "").trim().toLowerCase();
    if (analystTarget === "sandbox_cortex_emulator") return "Cortex Emulator";
    if (analystTarget === "snowflake_cortex_analyst") return "Snowflake Cortex Analyst";
    if (providerMode === "sandbox") return "Cortex Emulator";
    if (providerMode === "prod") return "Snowflake Cortex Analyst";
    return "Analyst Provider";
  }
  return String(entry?.provider ?? "provider unavailable");
}

function asLlmPromptEntries(step: TraceStep): LlmPromptEntry[] {
  const candidate = step.stageInput?.llmPrompts;
  if (!Array.isArray(candidate)) return [];
  return candidate.filter((entry): entry is LlmPromptEntry => Boolean(entry) && typeof entry === "object");
}

function asLlmResponseEntries(step: TraceStep): LlmResponseEntry[] {
  const candidate = step.stageOutput?.llmResponses;
  if (!Array.isArray(candidate)) return [];
  return candidate.filter((entry): entry is LlmResponseEntry => Boolean(entry) && typeof entry === "object");
}

function asStringValue(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function sqlPlanSteps(step: TraceStep): SqlPlanStepMeta[] {
  const ids = step.stageInput?.planStepIds;
  const goals = step.stageInput?.planGoals;
  if (!Array.isArray(ids)) return [];
  const steps: SqlPlanStepMeta[] = [];
  ids.forEach((id, index) => {
    const resolvedId = asStringValue(id);
    if (!resolvedId) return;
    const goalCandidate = Array.isArray(goals) ? goals[index] : undefined;
    steps.push({ id: resolvedId, goal: asStringValue(goalCandidate) });
  });
  return steps;
}

function llmExchangesForStep(step: TraceStep): LlmExchange[] {
  const prompts = asLlmPromptEntries(step);
  const responses = asLlmResponseEntries(step);
  const count = Math.max(prompts.length, responses.length);
  return Array.from({ length: count }).map((_, index) => {
    const prompt = prompts[index];
    const response = responses[index];
    const metadata =
      asRecord(prompt?.metadata) ??
      asRecord(response?.metadata) ??
      {};
    const stepId = asStringValue(metadata.stepId ?? metadata.step_id);
    const stepGoal = asStringValue(metadata.stepGoal ?? metadata.step_goal);
    return {
      index,
      prompt,
      response,
      stepId,
      stepGoal,
    };
  });
}

function sqlExchangeGroups(step: TraceStep, exchanges: LlmExchange[]): SqlExchangeGroup[] | null {
  if (step.id !== "t2" || exchanges.length === 0) return null;

  const plan = sqlPlanSteps(step);
  const grouped = new Map<string, LlmExchange[]>();
  for (const exchange of exchanges) {
    const key = exchange.stepId ?? "__unassigned__";
    const bucket = grouped.get(key);
    if (bucket) {
      bucket.push(exchange);
    } else {
      grouped.set(key, [exchange]);
    }
  }

  const groups: SqlExchangeGroup[] = [];
  const consumed = new Set<string>();

  for (let index = 0; index < plan.length; index += 1) {
    const planStep = plan[index];
    const planExchanges = grouped.get(planStep.id);
    if (!planExchanges || planExchanges.length === 0) continue;
    consumed.add(planStep.id);
    groups.push({
      key: planStep.id,
      title: `Step ${index + 1} (${planStep.id})`,
      goal: planStep.goal ?? planExchanges.find((item) => item.stepGoal)?.stepGoal,
      exchanges: planExchanges,
    });
  }

  const remaining = Array.from(grouped.entries())
    .filter(([key]) => key !== "__unassigned__" && !consumed.has(key))
    .map(([key, groupedExchanges]) => ({
      key,
      exchanges: groupedExchanges,
      firstIndex: groupedExchanges[0]?.index ?? Number.MAX_SAFE_INTEGER,
    }))
    .sort((a, b) => a.firstIndex - b.firstIndex);

  for (const entry of remaining) {
    groups.push({
      key: entry.key,
      title: `Step ${entry.key}`,
      goal: entry.exchanges.find((item) => item.stepGoal)?.stepGoal,
      exchanges: entry.exchanges,
    });
  }

  const unassigned = grouped.get("__unassigned__");
  if (unassigned && unassigned.length > 0) {
    groups.push({
      key: "__unassigned__",
      title: "Unassigned Exchanges",
      exchanges: unassigned,
    });
  }

  return groups.length > 0 ? groups : null;
}

function promptSections(prompt: LlmPromptEntry): PromptSection[] {
  const sections: PromptSection[] = [];
  if (typeof prompt.systemPrompt === "string" && prompt.systemPrompt.trim()) {
    sections.push({ label: "System", content: prompt.systemPrompt });
  }
  if (typeof prompt.userPrompt === "string" && prompt.userPrompt.trim()) {
    sections.push({ label: "User", content: prettyText(prompt.userPrompt) });
  }
  return sections;
}

function prettyText(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed === "object" && parsed !== null) return JSON.stringify(parsed, null, 2);
    return value;
  } catch {
    return value;
  }
}

function humanizeKey(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^./, (value) => value.toUpperCase());
}

function formatScalarValue(value: string | number | boolean | null): string {
  if (value === null) return "null";
  return String(value);
}

function appendMultilineBullet(lines: string[], bullet: string, value: string, indent: number): void {
  const prefix = " ".repeat(indent);
  const textLines = value.split("\n");
  lines.push(`${prefix}${bullet}${textLines[0] ?? ""}`);
  for (const line of textLines.slice(1)) {
    lines.push(`${prefix}  ${line}`);
  }
}

function formatMarkdownValue(lines: string[], value: unknown, indent = 0): void {
  const prefix = " ".repeat(indent);

  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    const scalar = typeof value === "string" ? prettyText(value) : formatScalarValue(value);
    appendMultilineBullet(lines, "- ", scalar, indent);
    return;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      lines.push(`${prefix}- []`);
      return;
    }
    value.forEach((item, index) => {
      if (item === null || typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
        const scalar = typeof item === "string" ? prettyText(item) : formatScalarValue(item);
        appendMultilineBullet(lines, `${index + 1}. `, scalar, indent);
        return;
      }

      lines.push(`${prefix}${index + 1}.`);
      formatMarkdownValue(lines, item, indent + 2);
    });
    return;
  }

  const record = asRecord(value);
  if (!record) return;
  const entries = Object.entries(record);
  if (!entries.length) {
    lines.push(`${prefix}- {}`);
    return;
  }
  for (const [key, nestedValue] of entries) {
    const label = humanizeKey(key);
    if (
      nestedValue === null ||
      typeof nestedValue === "string" ||
      typeof nestedValue === "number" ||
      typeof nestedValue === "boolean"
    ) {
      const scalar = typeof nestedValue === "string" ? prettyText(nestedValue) : formatScalarValue(nestedValue);
      appendMultilineBullet(lines, `- ${label}: `, scalar, indent);
      continue;
    }
    lines.push(`${prefix}- ${label}:`);
    formatMarkdownValue(lines, nestedValue, indent + 2);
  }
}

function parsedResponsePayload(response: LlmResponseEntry): Record<string, unknown> | null {
  if (response.parsedResponse && typeof response.parsedResponse === "object") {
    return response.parsedResponse;
  }
  const raw = asStringValue(response.rawResponse);
  if (!raw) return null;
  try {
    return asRecord(JSON.parse(raw));
  } catch {
    return null;
  }
}

const responseFieldOrder = [
  "relevance",
  "relevanceReason",
  "tooComplex",
  "type",
  "generationType",
  "lightResponse",
  "explanation",
  "clarificationQuestion",
  "notRelevantReason",
  "assumptions",
  "presentationIntent",
  "temporalScope",
  "tasks",
  "steps",
  "sql",
  "failedSql",
  "rows",
  "rowCount",
  "answer",
  "whyItMatters",
  "confidence",
  "confidenceReason",
  "summaryCards",
  "chartConfig",
  "tableConfig",
  "insights",
  "suggestedQuestions",
  "headline",
  "periodStart",
  "periodEnd",
  "periodLabel",
] as const;

function formattedResponseContent(response: LlmResponseEntry): string {
  const payload = parsedResponsePayload(response);
  const lines: string[] = [];
  const seen = new Set<string>();

  const pushSection = (title: string, value: unknown) => {
    if (value === undefined) return;
    lines.push(`## ${title}`);
    formatMarkdownValue(lines, value);
    lines.push("");
  };

  const payloadStrings = payload
    ? Object.values(payload).filter((value): value is string => typeof value === "string").map((value) => value.trim())
    : [];
  const shouldIncludeSummary =
    typeof response.humanResponse === "string" &&
    response.humanResponse.trim() &&
    !payloadStrings.some((value) => value === response.humanResponse?.trim());

  if (shouldIncludeSummary) {
    pushSection("Summary", response.humanResponse);
  }

  if (payload) {
    for (const key of responseFieldOrder) {
      if (!(key in payload)) continue;
      seen.add(key);
      pushSection(humanizeKey(key), payload[key]);
    }
    for (const [key, value] of Object.entries(payload)) {
      if (seen.has(key)) continue;
      pushSection(humanizeKey(key), value);
    }
  }

  if (!lines.length && response.error) return response.error;
  if (!lines.length && typeof response.rawResponse === "string" && response.rawResponse.trim()) {
    return prettyText(response.rawResponse);
  }
  while (lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n");
}

function responseContent(response: LlmResponseEntry): string {
  if (typeof response.rawResponse === "string" && response.rawResponse.trim()) {
    return prettyText(response.rawResponse);
  }
  return JSON.stringify(response.parsedResponse ?? {}, null, 2);
}

interface ExchangeSqlDetail {
  sql: string;
  failed: boolean;
}

function exchangeSqlFromResponse(response?: LlmResponseEntry): ExchangeSqlDetail | null {
  if (!response) return null;

  const parsed = asRecord(response.parsedResponse);
  const fromParsedFailedSql = asStringValue(parsed?.failedSql);
  if (fromParsedFailedSql) return { sql: fromParsedFailedSql, failed: true };
  const fromParsedSql = asStringValue(parsed?.sql);
  if (fromParsedSql) return { sql: fromParsedSql, failed: false };

  const raw = asStringValue(response.rawResponse);
  if (!raw) return null;
  try {
    const parsedRaw = asRecord(JSON.parse(raw));
    const fromRawFailedSql = asStringValue(parsedRaw?.failedSql);
    if (fromRawFailedSql) return { sql: fromRawFailedSql, failed: true };
    const fromRawSql = asStringValue(parsedRaw?.sql);
    if (fromRawSql) return { sql: fromRawSql, failed: false };
    return null;
  } catch {
    return null;
  }
}

function failedSqlForStep(step: TraceStep): string {
  if (step.status !== "blocked") return "";

  const fromTop = step.stageOutput?.["failedSql"];
  if (typeof fromTop === "string" && fromTop.trim()) return fromTop;

  const failureDetail = step.stageOutput?.["failureDetail"];
  if (failureDetail && typeof failureDetail === "object") {
    const fromDetail = (failureDetail as Record<string, unknown>).failedSql;
    if (typeof fromDetail === "string" && fromDetail.trim()) return fromDetail;
  }

  const responses = asLlmResponseEntries(step);
  for (const response of responses) {
    const parsed = response.parsedResponse;
    if (!parsed || typeof parsed !== "object") continue;
    const parsedRecord = parsed as Record<string, unknown>;
    const fromParsed = parsedRecord.failedSql;
    if (typeof fromParsed === "string" && fromParsed.trim()) return fromParsed;
    const parsedSql = parsedRecord.sql;
    if (typeof parsedSql === "string" && parsedSql.trim()) return parsedSql;
  }
  return "";
}

function LlmExchangeCard({
  exchange,
  exchangeLabel,
  stageFailed,
}: {
  exchange: LlmExchange;
  exchangeLabel: string;
  stageFailed: boolean;
}) {
  const prompt = exchange.prompt;
  const response = exchange.response;
  const sections = prompt ? promptSections(prompt) : [];
  const providerLabel = providerBadgeLabel(prompt ?? response);
  const exchangeSql = exchangeSqlFromResponse(response);
  const sqlLabel = exchangeSql ? (exchangeSql.failed || stageFailed ? "Failed SQL" : "Executed SQL") : "";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-[0_1px_6px_rgba(14,44,68,0.03)]">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-700">{exchangeLabel}</p>
        <span className="rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
          {providerLabel}
        </span>
      </div>
      {prompt ? (
        <>
          <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Prompt</p>
          <div className="mt-1 overflow-hidden rounded-md border border-slate-900 bg-slate-950">
            {sections.length ? (
              sections.map((section, sectionIndex) => (
                <div key={`${section.label}-${sectionIndex}`} className={sectionIndex > 0 ? "border-t border-slate-800" : ""}>
                  <div className="border-b border-slate-800 bg-slate-900 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                    {section.label}
                  </div>
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px] leading-relaxed text-slate-100">
                    <code>{section.content}</code>
                  </pre>
                </div>
              ))
            ) : (
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px] leading-relaxed text-slate-100">
                <code>{""}</code>
              </pre>
            )}
          </div>
        </>
      ) : null}
      {response ? (
        <>
          <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Response</p>
          <div className="mt-1 overflow-hidden rounded-md border border-slate-900 bg-slate-950">
            <div>
              <div className="border-b border-slate-800 bg-slate-900 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                Response (formatted)
              </div>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px] leading-relaxed text-slate-100">
                <code>{formattedResponseContent(response)}</code>
              </pre>
            </div>
            <div className="border-t border-slate-800">
              <div className="border-b border-slate-800 bg-slate-900 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                Response (structured json output)
              </div>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px] leading-relaxed text-slate-100">
                <code>{responseContent(response)}</code>
              </pre>
            </div>
          </div>
          {response.error ? <p className="mt-2 text-xs font-medium text-rose-700">Error: {response.error}</p> : null}
        </>
      ) : null}
      {exchangeSql ? (
        <>
          <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{sqlLabel}</p>
          <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-100">
            <code>{exchangeSql.sql}</code>
          </pre>
        </>
      ) : null}
    </div>
  );
}

export function AnalysisTrace({ steps }: { steps: TraceStep[] }) {
  const [open, setOpen] = useState(false);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white/85 p-4 shadow-[0_5px_14px_rgba(14,44,68,0.06)]">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold tracking-wide text-slate-900">Analysis Trace</h3>
          <p className="text-xs text-slate-600">Structured reasoning summary for auditability and trust.</p>
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          className="rounded-full border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-500"
          type="button"
        >
          {open ? "Hide trace" : "Show trace"}
        </button>
      </div>

      {open ? (
        <ol className="mt-4 space-y-3">
          {steps.map((step) => (
            <li key={step.id} className="rounded-xl border border-slate-200 bg-white p-3">
              {(() => {
                const exchanges = llmExchangesForStep(step);
                const groupedSqlExchanges = sqlExchangeGroups(step, exchanges);
                const failedSql = failedSqlForStep(step);
                const hasExchangeSql = exchanges.some((exchange) => Boolean(exchangeSqlFromResponse(exchange.response)));
                return (
                  <>
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-900">{step.title}</p>
                <div className="flex items-center gap-2">
                  {typeof step.runtimeMs === "number" ? (
                    <span className="rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
                      {`${step.runtimeMs.toFixed(1)} ms`}
                    </span>
                  ) : null}
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass[step.status]}`}>
                    {step.status}
                  </span>
                </div>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">{step.summary}</p>
              {exchanges.length ? (
                groupedSqlExchanges ? (
                  <div className="mt-3 space-y-3">
                    {groupedSqlExchanges.map((group) => (
                      <div key={group.key} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-xs font-semibold uppercase tracking-wide text-slate-700">{group.title}</p>
                          <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                            {group.exchanges.length} exchange{group.exchanges.length === 1 ? "" : "s"}
                          </span>
                        </div>
                        {group.goal ? <p className="mt-1 text-xs text-slate-600">{group.goal}</p> : null}
                        <div className="mt-2 space-y-2">
                          {group.exchanges.map((exchange, exchangeIndex) => (
                            <LlmExchangeCard
                              key={`${group.key}-exchange-${exchange.index}`}
                              exchange={exchange}
                              exchangeLabel={group.exchanges.length > 1 ? `LLM Exchange ${exchangeIndex + 1}` : "LLM Exchange"}
                              stageFailed={step.status === "blocked"}
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 space-y-3">
                    {exchanges.map((exchange, index) => (
                      <LlmExchangeCard
                        key={`llm-entry-${exchange.index}`}
                        exchange={exchange}
                        exchangeLabel={exchanges.length > 1 ? `LLM Exchange ${index + 1}` : "LLM Exchange"}
                        stageFailed={step.status === "blocked"}
                      />
                    ))}
                  </div>
                )
              ) : null}
              {failedSql && !hasExchangeSql ? (
                <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-rose-700">Failed SQL</p>
                  <pre className="mt-2 max-h-56 overflow-auto rounded bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-100">
                    <code>{failedSql}</code>
                  </pre>
                </div>
              ) : step.status === "blocked" && !hasExchangeSql ? (
                <p className="mt-3 text-xs text-slate-600">No SQL was attempted in this blocked path.</p>
              ) : null}
              {step.stageInput || step.stageOutput ? (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                    <div className="border-b border-slate-200 bg-slate-100 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                      State Input
                    </div>
                    <pre className="max-h-56 overflow-auto p-3 text-[11px] leading-relaxed text-slate-800">
                      <code>{renderPayload(step.stageInput)}</code>
                    </pre>
                  </div>
                  <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                    <div className="border-b border-slate-200 bg-slate-100 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                      State Output
                    </div>
                    <pre className="max-h-56 overflow-auto p-3 text-[11px] leading-relaxed text-slate-800">
                      <code>{renderPayload(step.stageOutput)}</code>
                    </pre>
                  </div>
                </div>
              ) : null}
              {step.qualityChecks?.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {step.qualityChecks.map((check) => (
                    <span key={check} className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-700">
                      {check}
                    </span>
                  ))}
                </div>
              ) : null}
                  </>
                );
              })()}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
