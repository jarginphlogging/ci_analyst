"use client";

import { useMemo, useState } from "react";
import { AnalysisTrace } from "@/components/analysis-trace";
import { DataExplorer } from "@/components/data-explorer";
import { EvidenceTable } from "@/components/evidence-table";
import { readNdjsonStream } from "@/lib/stream";
import type { AgentResponse, ChatMessage, ChatStreamEvent, DataTable, MetricPoint } from "@/lib/types";

const starterPrompts = [
  "What changed in charge-off risk this quarter by region?",
  "Where are fraud losses accelerating and why?",
  "Show deposit mix shifts that may pressure NIM.",
];

const sessionItems = [
  "Charge-Off Monitoring",
  "Fraud Operations Weekly",
  "Liquidity Watchlist",
  "Vintage Stress Deep Dive",
];

function formatMetric(metric: MetricPoint): string {
  if (metric.unit === "pct") return `${metric.value.toFixed(2)}%`;
  if (metric.unit === "bps") return `${metric.value.toFixed(0)} bps`;
  if (metric.unit === "usd") return `$${metric.value.toFixed(2)}B`;
  return metric.value.toFixed(0);
}

function formatDelta(metric: MetricPoint): string {
  if (metric.unit === "bps") return `${metric.delta > 0 ? "+" : ""}${metric.delta.toFixed(0)} bps`;
  if (metric.unit === "pct") return `${metric.delta > 0 ? "+" : ""}${metric.delta.toFixed(2)} pp`;
  if (metric.unit === "usd") return `${metric.delta > 0 ? "+" : ""}$${metric.delta.toFixed(2)}B`;
  return `${metric.delta > 0 ? "+" : ""}${metric.delta.toFixed(0)}`;
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

export function AgentWorkspace() {
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      text: "Ask any portfolio, fraud, or liquidity question. I will return a concise answer, audited analysis trace, and interactive evidence.",
      createdAt: "2026-02-16T13:00:00.000Z",
    },
  ]);

  const latestResponse = useMemo(
    () => [...messages].reverse().find((message) => message.role === "assistant" && message.response)?.response,
    [messages],
  );

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
        statusUpdates: ["Queued request"],
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
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            statusUpdates: [...(draft.statusUpdates ?? []), event.message],
          }));
          return;
        }

        if (event.type === "answer_delta") {
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            text: `${draft.text}${event.delta}`,
          }));
          return;
        }

        if (event.type === "response") {
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            text: event.response.answer,
            response: event.response,
          }));
          return;
        }

        if (event.type === "error") {
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            text: event.message,
            isStreaming: false,
            statusUpdates: [...(draft.statusUpdates ?? []), "Request failed"],
          }));
          return;
        }

        if (event.type === "done") {
          updateAssistantMessage(assistantMessageId, (draft) => ({
            ...draft,
            isStreaming: false,
          }));
        }
      });
    } catch {
      updateAssistantMessage(assistantMessageId, (draft) => ({
        ...draft,
        text: "I could not process that request. Please retry in a moment.",
        isStreaming: false,
        statusUpdates: [...(draft.statusUpdates ?? []), "Request failed"],
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
          <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">Analyst Console</p>
          <h1 className="mt-2 text-xl font-bold leading-tight">Cortex Conversational Analyst</h1>
          <p className="mt-2 text-sm text-slate-300">Fast governed answers with audit-ready reasoning summaries.</p>

          <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-800/70 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-400">System Status</p>
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Azure OpenAI + Cortex Analyst connected
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
          <header className="rounded-2xl border border-slate-200 bg-white/85 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Banking Risk Intelligence</p>
                <h2 className="text-xl font-bold text-slate-900">Conversation Workspace</h2>
              </div>
              <div className="flex items-center gap-2 rounded-full border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700">
                <span className="h-2 w-2 rounded-full bg-emerald-400" />
                Deterministic Workflow + Bounded Agentic Reasoning
              </div>
            </div>
          </header>

          <section className="mt-4 flex-1 space-y-4 overflow-y-auto pr-1">
            {messages.map((message) => {
              if (message.role === "user") {
                return (
                  <article key={message.id} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-slate-900 px-4 py-3 text-sm text-slate-100 shadow">
                      <p>{message.text}</p>
                      <p className="mt-2 text-[11px] uppercase tracking-wide text-slate-400">{messageTime(message.createdAt)}</p>
                    </div>
                  </article>
                );
              }

              return (
                <article key={message.id} className="animate-fade-up space-y-3 rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-xs uppercase tracking-[0.16em] text-cyan-700">Agent Response</p>
                      <p className="text-sm text-slate-600">{messageTime(message.createdAt)}</p>
                    </div>
                    {message.response ? (
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

                  <p className="text-lg font-semibold leading-snug text-slate-950">{message.text || "..."}</p>

                  {message.isStreaming ? (
                    <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-cyan-800">Live reasoning trace</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {(message.statusUpdates ?? []).slice(-8).map((status, index) => (
                          <span key={`${status}-${index}`} className="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-cyan-800">
                            {status}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {message.response ? (
                    <>
                      <section className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                        <p className="text-xs uppercase tracking-wide text-slate-500">Why It Matters</p>
                        <p className="mt-1.5 text-sm text-slate-700">{message.response.whyItMatters}</p>
                      </section>

                      <section className="grid gap-3 sm:grid-cols-3">
                        {message.response.metrics.map((metric) => (
                          <div key={metric.label} className="rounded-xl border border-slate-200 bg-white p-3">
                            <p className="text-xs uppercase tracking-wide text-slate-500">{metric.label}</p>
                            <p className="mt-2 text-xl font-bold text-slate-900">{formatMetric(metric)}</p>
                            <p className={`mt-1 text-xs font-semibold ${metric.delta >= 0 ? "text-rose-700" : "text-emerald-700"}`}>
                              {formatDelta(metric)}
                            </p>
                          </div>
                        ))}
                      </section>

                      <EvidenceTable rows={message.response.evidence} />
                      <DataExplorer tables={buildRenderableTables(message.response)} />

                      <section className="rounded-2xl border border-slate-200 bg-white/85 p-4">
                        <h3 className="text-sm font-semibold tracking-wide text-slate-900">Priority Insights</h3>
                        <div className="mt-3 grid gap-2 md:grid-cols-3">
                          {message.response.insights.map((insight) => (
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
                          <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
                            {message.response.assumptions.map((item) => (
                              <li key={item}>- {item}</li>
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
                  ) : null}
                </article>
              );
            })}

            {isLoading ? (
              <article className="animate-fade-up rounded-2xl border border-cyan-200 bg-cyan-50 p-4">
                <p className="text-sm font-semibold text-cyan-900">Streaming analysis in progress...</p>
                <p className="mt-1 text-sm text-cyan-800">Response appears token-by-token while the governed pipeline runs validation.</p>
              </article>
            ) : null}
          </section>

          <footer className="mt-4 rounded-2xl border border-slate-200 bg-white/85 p-3">
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
                placeholder="Ask a complex banking analytics question..."
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
          <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Active Brief</h3>
          <p className="mt-2 text-lg font-semibold text-slate-900">Decision Snapshot</p>
          <p className="mt-1 text-sm text-slate-700">
            Keep this panel open to review the current answer, confidence context, and fastest next actions.
          </p>

          {latestResponse ? (
            <div className="mt-4 space-y-3">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Top Signal</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">{latestResponse.insights[0]?.title ?? "No insight yet"}</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Confidence Basis</p>
                <p className="mt-1 text-sm text-slate-700">
                  {latestResponse.confidence === "high"
                    ? "QA checks passed with consistent segment reconciliation."
                    : latestResponse.confidence === "medium"
                      ? "Minor assumptions exist; decision-grade but verify downstream impact."
                      : "Incomplete context requires clarifying constraints before acting."}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Next Action</p>
                <p className="mt-1 text-sm text-slate-700">
                  Use one suggested follow-up to isolate root cause and convert this into an intervention plan.
                </p>
              </div>
            </div>
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
