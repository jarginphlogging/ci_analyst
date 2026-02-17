"use client";

import { useMemo, useState } from "react";
import type { EvidenceRow } from "@/lib/types";

type SortKey = "segment" | "prior" | "current" | "changeBps" | "contribution";

const sortOptions: { key: SortKey; label: string }[] = [
  { key: "contribution", label: "Contribution" },
  { key: "changeBps", label: "Change (bps)" },
  { key: "current", label: "Current Rate" },
  { key: "segment", label: "Segment" },
];

function contributionWidth(value: number): number {
  return Math.max(8, Math.min(100, Math.round(value * 140)));
}

export function EvidenceTable({ rows }: { rows: EvidenceRow[] }) {
  const [sortBy, setSortBy] = useState<SortKey>("contribution");

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      if (sortBy === "segment") return a.segment.localeCompare(b.segment);
      return Number(b[sortBy]) - Number(a[sortBy]);
    });
  }, [rows, sortBy]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold tracking-wide text-slate-900">Driver Breakdown</h3>
          <p className="text-xs text-slate-600">Interactive evidence ranked by impact.</p>
        </div>
        <div className="inline-flex items-center rounded-full bg-slate-100 p-1">
          {sortOptions.map((option) => (
            <button
              key={option.key}
              onClick={() => setSortBy(option.key)}
              className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${
                sortBy === option.key ? "bg-white text-slate-900 shadow" : "text-slate-600 hover:text-slate-900"
              }`}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[580px] border-separate border-spacing-y-2 text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500">
              <th className="px-2 py-1">Segment</th>
              <th className="px-2 py-1">Prior</th>
              <th className="px-2 py-1">Current</th>
              <th className="px-2 py-1">Delta (bps)</th>
              <th className="px-2 py-1">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.segment} className="rounded-xl bg-slate-50 text-slate-800">
                <td className="rounded-l-xl px-2 py-2 font-medium">{row.segment}</td>
                <td className="px-2 py-2">{row.prior.toFixed(2)}%</td>
                <td className="px-2 py-2">{row.current.toFixed(2)}%</td>
                <td className="px-2 py-2">{row.changeBps}</td>
                <td className="rounded-r-xl px-2 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 w-28 rounded-full bg-slate-200">
                      <div
                        className="h-2.5 rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500"
                        style={{ width: `${contributionWidth(Math.abs(row.contribution))}%` }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-slate-700">{(row.contribution * 100).toFixed(0)}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
