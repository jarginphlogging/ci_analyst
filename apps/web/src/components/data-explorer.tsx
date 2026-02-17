"use client";

import { useMemo, useState } from "react";
import type { DataCell, DataTable } from "@/lib/types";

function formatCell(value: DataCell): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  return value;
}

function escapeCsv(value: DataCell): string {
  const text = value === null ? "" : String(value);
  if (!/[",\n]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

function toCsv(table: DataTable): string {
  const header = table.columns.map((column) => escapeCsv(column)).join(",");
  const rows = table.rows.map((row) => table.columns.map((column) => escapeCsv(row[column] ?? null)).join(","));
  return [header, ...rows].join("\n");
}

function triggerDownload(fileName: string, content: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function DataExplorer({ tables }: { tables: DataTable[] }) {
  const [activeId, setActiveId] = useState(tables[0]?.id ?? "");

  const selected = useMemo(() => tables.find((table) => table.id === activeId) ?? tables[0], [tables, activeId]);

  if (!selected) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">Retrieved Data</h3>
        <p className="mt-2 text-sm text-slate-600">No tabular artifacts were returned for this query.</p>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold tracking-wide text-slate-900">Retrieved Data</h3>
          <p className="text-xs text-slate-600">View and export raw tables used in the analysis.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-700">
            {selected.rowCount} rows
          </span>
          <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-700">
            {selected.columns.length} columns
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select
          value={selected.id}
          onChange={(event) => setActiveId(event.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-medium text-slate-800"
        >
          {tables.map((table) => (
            <option key={table.id} value={table.id}>
              {table.name}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => triggerDownload(`${selected.id}.csv`, toCsv(selected), "text/csv;charset=utf-8")}
          className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-500 hover:text-cyan-800"
        >
          Export CSV
        </button>

        <button
          type="button"
          onClick={() =>
            triggerDownload(`${selected.id}.json`, JSON.stringify(selected.rows, null, 2), "application/json;charset=utf-8")
          }
          className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-500 hover:text-cyan-800"
        >
          Export JSON
        </button>
      </div>

      {selected.description ? <p className="mt-2 text-xs text-slate-600">{selected.description}</p> : null}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[760px] border-separate border-spacing-y-1.5 text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500">
              {selected.columns.map((column) => (
                <th key={column} className="px-2 py-1">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {selected.rows.map((row, index) => (
              <tr key={`${selected.id}-${index}`} className="rounded-xl bg-slate-50 text-slate-800">
                {selected.columns.map((column, idx) => (
                  <td
                    key={`${selected.id}-${index}-${column}`}
                    className={`px-2 py-2 text-sm ${idx === 0 ? "rounded-l-xl font-medium" : ""} ${
                      idx === selected.columns.length - 1 ? "rounded-r-xl" : ""
                    }`}
                  >
                    {formatCell(row[column] ?? null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected.sourceSql ? (
        <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-2">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">Source SQL</summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-100">
            <code>{selected.sourceSql}</code>
          </pre>
        </details>
      ) : null}
    </section>
  );
}
