"use client";

import { useMemo } from "react";
import type { ChartConfig, DataCell, DataTable, PrimaryVisual, TableConfig } from "@/lib/types";

interface ChartSeries {
  key: string;
  points: Array<{ x: string; y: number | null }>;
}

function asNumber(value: DataCell | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function prettify(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function isTimeLike(value: DataCell | undefined): boolean {
  if (typeof value !== "string") return false;
  const raw = value.trim();
  if (!raw) return false;
  if (raw.length >= 10 && raw[4] === "-" && raw[7] === "-") return true;
  return Number.isFinite(Date.parse(raw));
}

function compareCells(a: DataCell | undefined, b: DataCell | undefined): number {
  const aNumber = asNumber(a);
  const bNumber = asNumber(b);
  if (aNumber !== null && bNumber !== null) return aNumber - bNumber;
  const aDate = isTimeLike(a) ? Date.parse(String(a)) : Number.NaN;
  const bDate = isTimeLike(b) ? Date.parse(String(b)) : Number.NaN;
  if (Number.isFinite(aDate) && Number.isFinite(bDate)) return aDate - bDate;
  return String(a ?? "").localeCompare(String(b ?? ""));
}

function formatValue(value: number | null, kind: ChartConfig["yFormat"] | TableConfig["columns"][number]["format"]): string {
  if (value === null) return "-";
  if (kind === "currency") return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  if (kind === "percent") {
    const normalized = Math.abs(value) <= 1 ? value * 100 : value;
    return `${normalized.toFixed(Math.abs(normalized) >= 10 ? 1 : 2)}%`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatCell(value: DataCell, format: TableConfig["columns"][number]["format"]): string {
  if (value === null) return "-";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (format === "string") return String(value);
  if (format === "date") {
    if (typeof value !== "string") return String(value);
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleDateString();
  }
  return formatValue(asNumber(value), format);
}

function chartSeriesFromTable(table: DataTable, config: ChartConfig): ChartSeries[] {
  const xKey = config.x;
  const yKeys = Array.isArray(config.y) ? config.y : [config.y];

  if (!config.series || yKeys.length > 1) {
    return yKeys.map((yKey) => ({
      key: yKey,
      points: table.rows.map((row) => ({
        x: String(row[xKey] ?? ""),
        y: asNumber(row[yKey]),
      })),
    }));
  }

  const grouped = new Map<string, Record<string, number | null>>();
  const seriesValues = new Set<string>();
  for (const row of table.rows) {
    const x = String(row[xKey] ?? "");
    const seriesValue = String(row[config.series] ?? "");
    if (!grouped.has(x)) grouped.set(x, {});
    grouped.get(x)![seriesValue] = asNumber(row[yKeys[0]]);
    seriesValues.add(seriesValue);
  }

  const sortedX = Array.from(grouped.keys()).sort((a, b) => compareCells(a, b));
  return Array.from(seriesValues).map((seriesValue) => ({
    key: seriesValue,
    points: sortedX.map((x) => ({
      x,
      y: grouped.get(x)?.[seriesValue] ?? null,
    })),
  }));
}

function LineChart({ table, config }: { table: DataTable; config: ChartConfig }) {
  const series = useMemo(() => chartSeriesFromTable(table, config), [table, config]);
  const width = 860;
  const height = 280;
  const padding = 24;
  const allValues = series.flatMap((entry) => entry.points.map((point) => point.y).filter((value): value is number => value !== null));
  const max = allValues.length ? Math.max(...allValues) : 1;
  const min = allValues.length ? Math.min(...allValues) : 0;
  const range = Math.max(1, max - min);
  const pointCount = Math.max(1, series[0]?.points.length ?? 1);
  const stepX = (width - padding * 2) / Math.max(1, pointCount - 1);
  const colors = ["#0ea5e9", "#f97316", "#10b981", "#ef4444", "#6366f1", "#14b8a6"];

  return (
    <div className="mt-3 rounded-2xl border border-slate-200 bg-white/90 p-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-72 w-full">
        <rect x={0} y={0} width={width} height={height} fill="transparent" />
        {series.map((entry, idx) => {
          const points = entry.points
            .map((point, pointIdx) => {
              if (point.y === null) return null;
              const x = padding + pointIdx * stepX;
              const y = padding + ((max - point.y) / range) * (height - padding * 2);
              return `${x},${y}`;
            })
            .filter((point): point is string => point !== null);
          if (points.length < 2) return null;
          return (
            <polyline
              key={entry.key}
              points={points.join(" ")}
              fill="none"
              stroke={colors[idx % colors.length]}
              strokeWidth={2.5}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-700">
        {series.map((entry, idx) => (
          <span key={entry.key} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 font-semibold">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors[idx % colors.length] }} />
            {prettify(entry.key)}
          </span>
        ))}
      </div>
    </div>
  );
}

function BarChart({ table, config }: { table: DataTable; config: ChartConfig }) {
  const series = useMemo(() => chartSeriesFromTable(table, config), [table, config]);
  const xValues = series[0]?.points.map((point) => point.x) ?? [];
  const maxValue = Math.max(
    1,
    ...series.flatMap((entry) => entry.points.map((point) => point.y).filter((value): value is number => value !== null)),
  );
  const colors = ["bg-sky-500", "bg-orange-500", "bg-emerald-500", "bg-rose-500", "bg-indigo-500", "bg-cyan-500"];
  return (
    <div className="mt-3 space-y-3 rounded-2xl border border-slate-200 bg-white/90 p-3">
      {xValues.map((x, idx) => (
        <div key={`${x}-${idx}`} className="rounded-xl border border-slate-200 bg-slate-50 p-2">
          <p className="text-xs font-semibold text-slate-700">{x}</p>
          <div className="mt-1.5 space-y-1.5">
            {series.map((entry, seriesIdx) => {
              const value = entry.points[idx]?.y ?? null;
              const widthPct = value === null ? 0 : Math.max(0, Math.min(100, (value / maxValue) * 100));
              return (
                <div key={`${x}-${entry.key}`} className="grid grid-cols-[140px_minmax(0,1fr)_100px] items-center gap-2 text-xs">
                  <span className="font-medium text-slate-700">{prettify(entry.key)}</span>
                  <div className="h-2.5 rounded-full bg-slate-200">
                    <div className={`h-2.5 rounded-full ${colors[seriesIdx % colors.length]}`} style={{ width: `${widthPct}%` }} />
                  </div>
                  <span className="text-right font-semibold text-slate-700">{formatValue(value, config.yFormat ?? "number")}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function ChartPanel({ table, config }: { table: DataTable; config: ChartConfig }) {
  const title = `${config.yLabel || prettify(Array.isArray(config.y) ? config.y[0] : config.y)} by ${config.xLabel || prettify(config.x)}`;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">{title}</h3>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
          {config.type.replace("_", " ")}
        </span>
      </div>
      {config.type === "line" ? <LineChart table={table} config={config} /> : <BarChart table={table} config={config} />}
    </section>
  );
}

function sortedRows(table: DataTable, tableConfig: TableConfig | null | undefined): Array<Record<string, DataCell>> {
  if (!tableConfig?.sortBy) return table.rows;
  const direction = tableConfig.sortDir === "asc" ? 1 : -1;
  return [...table.rows].sort((left, right) => direction * compareCells(left[tableConfig.sortBy ?? ""], right[tableConfig.sortBy ?? ""]));
}

function TablePanel({ table, tableConfig }: { table: DataTable; tableConfig: TableConfig | null | undefined }) {
  const columns = tableConfig?.columns?.length
    ? tableConfig.columns
    : table.columns.map((column) => ({ key: column, label: prettify(column), format: "string" as const, align: "left" as const }));
  const rows = useMemo(() => sortedRows(table, tableConfig), [table, tableConfig]);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">Primary Data Table</h3>
        {tableConfig?.style ? (
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
            {tableConfig.style}
          </span>
        ) : null}
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[760px] border-separate border-spacing-y-1.5 text-left text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
              {columns.map((column) => (
                <th key={column.key} className={`px-2 py-1 ${column.align === "right" ? "text-right" : "text-left"}`}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIdx) => (
              <tr key={`row-${rowIdx}`} className="rounded-xl bg-slate-50 text-slate-800">
                {columns.map((column, colIdx) => (
                  <td
                    key={`${rowIdx}-${column.key}`}
                    className={`px-2 py-2 text-sm ${column.align === "right" ? "text-right" : "text-left"} ${
                      colIdx === 0 ? "rounded-l-xl" : ""
                    } ${colIdx === columns.length - 1 ? "rounded-r-xl" : ""}`}
                  >
                    {formatCell(row[column.key] ?? null, column.format)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function EvidenceTable({
  chartConfig,
  tableConfig,
  primaryVisual,
  dataTables,
}: {
  chartConfig?: ChartConfig | null;
  tableConfig?: TableConfig | null;
  primaryVisual?: PrimaryVisual;
  dataTables?: DataTable[];
}) {
  const table = dataTables?.[0];
  if (!table) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">{primaryVisual?.title?.trim() || "Visualization"}</h3>
        <p className="mt-2 text-sm text-slate-600">No tabular output was returned for this request.</p>
      </section>
    );
  }

  if (chartConfig) {
    return <ChartPanel table={table} config={chartConfig} />;
  }
  return <TablePanel table={table} tableConfig={tableConfig} />;
}
