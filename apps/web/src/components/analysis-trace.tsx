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
    return JSON.stringify(payload, null, 2);
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
  rawResponse?: string | null;
  parsedResponse?: Record<string, unknown> | null;
  error?: string | null;
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

export function AnalysisTrace({ steps }: { steps: TraceStep[] }) {
  const [open, setOpen] = useState(false);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white/85 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
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
                const llmPrompts = asLlmPromptEntries(step);
                const llmResponses = asLlmResponseEntries(step);
                return (
                  <>
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-900">{step.title}</p>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass[step.status]}`}>
                  {step.status}
                </span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">{step.summary}</p>
              {llmPrompts.length ? (
                <div className="mt-3 space-y-3">
                  {llmPrompts.map((prompt, index) => (
                    <div key={`prompt-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                        LLM Prompt {index + 1} ({prompt.provider ?? "llm"})
                      </p>
                      <pre className="mt-2 max-h-56 overflow-auto rounded bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-100">
                        <code>{prompt.systemPrompt ?? ""}</code>
                      </pre>
                      <pre className="mt-2 max-h-56 overflow-auto rounded bg-slate-900 p-2 text-[11px] leading-relaxed text-slate-100">
                        <code>{prompt.userPrompt ?? ""}</code>
                      </pre>
                    </div>
                  ))}
                </div>
              ) : null}
              {llmResponses.length ? (
                <div className="mt-3 space-y-3">
                  {llmResponses.map((response, index) => (
                    <div key={`response-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                        LLM Response {index + 1} ({response.provider ?? "llm"})
                      </p>
                      <pre className="mt-2 max-h-56 overflow-auto rounded bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-100">
                        <code>{response.rawResponse ?? JSON.stringify(response.parsedResponse ?? {}, null, 2)}</code>
                      </pre>
                      {response.error ? (
                        <p className="mt-2 text-xs font-medium text-rose-700">Error: {response.error}</p>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
              {step.sql ? (
                <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs leading-relaxed text-slate-100">
                  <code>{step.sql}</code>
                </pre>
              ) : null}
              {step.stageInput || step.stageOutput ? (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                    <div className="border-b border-slate-200 bg-slate-100 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                      Input
                    </div>
                    <pre className="max-h-56 overflow-auto p-3 text-[11px] leading-relaxed text-slate-800">
                      <code>{renderPayload(step.stageInput)}</code>
                    </pre>
                  </div>
                  <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                    <div className="border-b border-slate-200 bg-slate-100 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                      Output
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
