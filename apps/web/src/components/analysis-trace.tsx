"use client";

import { useState } from "react";
import type { TraceStep } from "@/lib/types";

const statusClass: Record<TraceStep["status"], string> = {
  done: "bg-emerald-100 text-emerald-800 border-emerald-200",
  running: "bg-amber-100 text-amber-800 border-amber-200",
  blocked: "bg-rose-100 text-rose-800 border-rose-200",
};

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
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-900">{step.title}</p>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass[step.status]}`}>
                  {step.status}
                </span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">{step.summary}</p>
              {step.sql ? (
                <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs leading-relaxed text-slate-100">
                  <code>{step.sql}</code>
                </pre>
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
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
