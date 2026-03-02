"use client";

import { useMemo } from "react";
import type { ChartConfig, DataCell, DataTable, PrimaryVisual, TableConfig } from "@/lib/types";

interface ChartPoint {
  x: string;
  y: number | null;
}

interface ChartSeries {
  key: string;
  points: ChartPoint[];
}

interface ChartReadiness {
  ok: boolean;
  reason: string;
}

const CHART_COLORS = ["#0284c7", "#ea580c", "#059669", "#dc2626", "#4338ca", "#0f766e"];

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

function formatValue(
  value: number | null,
  kind: ChartConfig["yFormat"] | TableConfig["columns"][number]["format"],
): string {
  if (value === null) return "-";
  if (kind === "currency") {
    return value.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }
  if (kind === "percent") {
    const normalized = Math.abs(value) <= 1 ? value * 100 : value;
    return `${normalized.toFixed(Math.abs(normalized) >= 10 ? 1 : 2)}%`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatAxisValue(value: number, kind: ChartConfig["yFormat"] | undefined): string {
  const effective = kind ?? "number";
  if (effective === "currency") {
    if (Math.abs(value) >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
    if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
    return formatValue(value, "currency");
  }
  if (effective === "percent") return formatValue(value, "percent");
  if (Math.abs(value) >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return formatValue(value, "number");
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

function formatXLabel(value: string): string {
  if (!isTimeLike(value)) return value;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    year: parsed.getUTCDate() === 1 ? "numeric" : undefined,
    day: parsed.getUTCDate() === 1 ? undefined : "numeric",
  });
}

function chartRows(table: DataTable, xKey: string): Array<Record<string, DataCell>> {
  return [...table.rows].sort((left, right) => compareCells(left[xKey], right[xKey]));
}

function chartSeriesFromTable(table: DataTable, config: ChartConfig): ChartSeries[] {
  const xKey = config.x;
  const yKeys = Array.isArray(config.y) ? config.y : [config.y];
  const rows = chartRows(table, xKey);

  if (!config.series || yKeys.length > 1) {
    return yKeys.map((yKey) => ({
      key: yKey,
      points: rows.map((row) => ({
        x: String(row[xKey] ?? ""),
        y: asNumber(row[yKey]),
      })),
    }));
  }

  const grouped = new Map<string, Record<string, number | null>>();
  const seriesValues = new Set<string>();
  for (const row of rows) {
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

function evaluateChartReadiness(table: DataTable, config: ChartConfig): ChartReadiness {
  if (!table.columns.includes(config.x)) {
    return { ok: false, reason: "Chart downgraded to table: x-axis column is missing." };
  }
  const yKeys = Array.isArray(config.y) ? config.y : [config.y];
  if (!yKeys.length || yKeys.some((key) => !table.columns.includes(key))) {
    return { ok: false, reason: "Chart downgraded to table: y-axis column is missing." };
  }

  const rows = chartRows(table, config.x);
  const distinctX = new Set(rows.map((row) => String(row[config.x] ?? "")));
  if (distinctX.size < 2) {
    return { ok: false, reason: "Chart downgraded to table: not enough x-axis points." };
  }
  if (config.type === "line" && distinctX.size < 3) {
    return { ok: false, reason: "Chart downgraded to table: line charts need at least 3 points." };
  }
  if (config.series) {
    const seriesCount = new Set(rows.map((row) => String(row[config.series ?? ""] ?? ""))).size;
    if (seriesCount > 10) {
      return { ok: false, reason: "Chart downgraded to table: too many series for reliable reading." };
    }
  }

  const numericCount = yKeys.reduce((count, key) => {
    return count + rows.filter((row) => asNumber(row[key]) !== null).length;
  }, 0);
  if (numericCount < 2) {
    return { ok: false, reason: "Chart downgraded to table: insufficient numeric data points." };
  }
  return { ok: true, reason: "" };
}

function yTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0];
  if (Math.abs(max - min) < Number.EPSILON) return [min];
  const step = (max - min) / Math.max(1, count - 1);
  return Array.from({ length: count }, (_, idx) => min + step * idx);
}

function linePath(points: ChartPoint[], xOf: (idx: number) => number, yOf: (value: number) => number): string {
  let path = "";
  let started = false;
  points.forEach((point, idx) => {
    if (point.y === null) {
      started = false;
      return;
    }
    const x = xOf(idx);
    const y = yOf(point.y);
    path += `${started ? "L" : "M"}${x},${y} `;
    started = true;
  });
  return path.trim();
}

function areaPath(
  points: ChartPoint[],
  xOf: (idx: number) => number,
  yOf: (value: number) => number,
  baselineValue: number,
): string {
  const valid = points
    .map((point, idx) => ({ idx, point }))
    .filter((entry): entry is { idx: number; point: { x: string; y: number } } => entry.point.y !== null);
  if (valid.length < 2) return "";
  const top = valid.map(({ idx, point }) => `${xOf(idx)},${yOf(point.y)}`).join(" ");
  const baseline = valid
    .slice()
    .reverse()
    .map(({ idx }) => `${xOf(idx)},${yOf(baselineValue)}`)
    .join(" ");
  return `M ${top} L ${baseline} Z`;
}

function AreaChart({ table, config }: { table: DataTable; config: ChartConfig }) {
  const series = useMemo(() => chartSeriesFromTable(table, config), [table, config]);
  const width = 960;
  const height = 320;
  const margin = { top: 8, right: 18, bottom: 34, left: 92 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const pointCount = Math.max(1, series[0]?.points.length ?? 1);
  const stacked = config.type === "stacked_bar" && series.length > 1;
  const stackedTotals = stacked
    ? Array.from({ length: pointCount }, (_, idx) =>
        series.reduce((sum, entry) => {
          const value = entry.points[idx]?.y;
          return sum + (value !== null && Number.isFinite(value) ? Math.max(0, value) : 0);
        }, 0),
      )
    : [];
  const allValues = stacked
    ? stackedTotals
    : series.flatMap((entry) => entry.points.map((point) => point.y).filter((value): value is number => value !== null));
  const maxRaw = allValues.length ? Math.max(...allValues) : 1;
  const minRaw = stacked ? 0 : allValues.length ? Math.min(...allValues) : 0;
  const padded = Math.max(1, (maxRaw - minRaw) * 0.08, Math.abs(maxRaw) * 0.02);
  const anchorAtZero = stacked || (minRaw >= 0 && maxRaw > 0 && minRaw / maxRaw < 0.2);
  const domainMin = anchorAtZero ? 0 : minRaw - padded;
  const domainMax = maxRaw + padded;
  const yRange = Math.max(1, domainMax - domainMin);
  const xStep = pointCount === 1 ? 0 : plotWidth / (pointCount - 1);
  const ticksY = yTicks(domainMin, domainMax, 4);
  const xTickCount = Math.min(4, pointCount);
  const xTickIndexes = Array.from({ length: xTickCount }, (_, idx) =>
    Math.round((idx * Math.max(0, pointCount - 1)) / Math.max(1, xTickCount - 1)),
  ).filter((value, idx, arr) => arr.indexOf(value) === idx);

  const xOf = (idx: number): number => margin.left + idx * xStep;
  const yOf = (value: number): number => margin.top + ((domainMax - value) / yRange) * plotHeight;
  const baseLineValue = anchorAtZero ? 0 : domainMin;
  const stackedTopBySeries: Array<number[]> = [];
  const stackedBottomBySeries: Array<number[]> = [];
  if (stacked) {
    const running = Array.from({ length: pointCount }, () => 0);
    series.forEach((entry, seriesIdx) => {
      stackedBottomBySeries[seriesIdx] = [...running];
      stackedTopBySeries[seriesIdx] = running.map((base, idx) => {
        const value = entry.points[idx]?.y;
        return base + (value !== null && Number.isFinite(value) ? Math.max(0, value) : 0);
      });
      stackedTopBySeries[seriesIdx].forEach((value, idx) => {
        running[idx] = value;
      });
    });
  }

  return (
    <div className="mt-1">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[300px] w-full">
        <rect x={0} y={0} width={width} height={height} fill="transparent" />

        {ticksY.map((tick) => {
          const y = yOf(tick);
          return (
            <g key={`y-${tick}`}>
              <line x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="#e2e8f0" strokeWidth={0.8} />
              <text x={margin.left - 12} y={y + 4} textAnchor="end" fontSize="17" fill="#64748b">
                {formatAxisValue(tick, config.yFormat)}
              </text>
            </g>
          );
        })}

        <line
          x1={margin.left}
          x2={margin.left}
          y1={margin.top}
          y2={height - margin.bottom}
          stroke="#94a3b8"
          strokeWidth={0.9}
        />
        <line
          x1={margin.left}
          x2={width - margin.right}
          y1={height - margin.bottom}
          y2={height - margin.bottom}
          stroke="#94a3b8"
          strokeWidth={0.9}
        />

        {xTickIndexes.map((tickIdx) => {
          const label = series[0]?.points[tickIdx]?.x ?? "";
          const x = xOf(tickIdx);
          return (
            <g key={`x-${tickIdx}`}>
              <line
                x1={x}
                x2={x}
                y1={height - margin.bottom}
                y2={height - margin.bottom + 5}
                stroke="#94a3b8"
                strokeWidth={0.9}
              />
              <text x={x} y={height - margin.bottom + 20} textAnchor="middle" fontSize="16" fill="#64748b">
                {formatXLabel(label)}
              </text>
            </g>
          );
        })}

        {series.map((entry, idx) => {
          const color = CHART_COLORS[idx % CHART_COLORS.length];
          const path = linePath(entry.points, xOf, yOf);
          if (!path) return null;
          const fillPath = stacked
            ? (() => {
                const top = stackedTopBySeries[idx];
                const bottom = stackedBottomBySeries[idx];
                if (!top || !bottom) return "";
                const topLine = top.map((value, pointIdx) => `${xOf(pointIdx)},${yOf(value)}`).join(" ");
                const bottomLine = bottom
                  .slice()
                  .reverse()
                  .map((value, revIdx) => {
                    const pointIdx = bottom.length - 1 - revIdx;
                    return `${xOf(pointIdx)},${yOf(value)}`;
                  })
                  .join(" ");
                return `M ${topLine} L ${bottomLine} Z`;
              })()
            : areaPath(entry.points, xOf, yOf, baseLineValue);
          return (
            <g key={entry.key}>
              {fillPath ? <path d={fillPath} fill={color} fillOpacity={stacked ? 0.52 : 0.16} stroke="none" /> : null}
              <path d={path} fill="none" stroke={color} strokeWidth={2.2} strokeLinejoin="round" strokeLinecap="round" />
              {entry.points.map((point, pointIdx) => {
                if (point.y === null) return null;
                const x = xOf(pointIdx);
                const y = yOf(point.y);
                const isLatest = pointIdx === entry.points.length - 1;
                if (!isLatest && pointIdx % 3 !== 0) return null;
                return (
                  <circle
                    key={`${entry.key}-${pointIdx}`}
                    cx={x}
                    cy={y}
                    r={isLatest ? 3.4 : 2.2}
                    fill={color}
                    stroke="#ffffff"
                    strokeWidth={1}
                  >
                    <title>{`${prettify(entry.key)} | ${formatXLabel(point.x)}: ${formatValue(point.y, config.yFormat ?? "number")}`}</title>
                  </circle>
                );
              })}
            </g>
          );
        })}

      </svg>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-700">
        {series.map((entry, idx) => (
          <span
            key={entry.key}
            className={`inline-flex items-center gap-1.5 font-medium ${
              series.length === 1
                ? "rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[15px] text-slate-700"
                : ""
            }`}
          >
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: CHART_COLORS[idx % CHART_COLORS.length] }} />
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
  return (
    <div className="mt-3 space-y-3 rounded-2xl border border-slate-200 bg-white p-3">
      {xValues.map((x, idx) => (
        <div key={`${x}-${idx}`} className="rounded-xl border border-slate-200 bg-slate-50 p-2.5">
          <p className="text-xs font-semibold text-slate-700">{formatXLabel(x)}</p>
          <div className="mt-1.5 space-y-1.5">
            {series.map((entry, seriesIdx) => {
              const value = entry.points[idx]?.y ?? null;
              const widthPct = value === null ? 0 : Math.max(0, Math.min(100, (value / maxValue) * 100));
              const color = CHART_COLORS[seriesIdx % CHART_COLORS.length];
              return (
                <div key={`${x}-${entry.key}`} className="grid grid-cols-[140px_minmax(0,1fr)_120px] items-center gap-2 text-xs">
                  <span className="font-medium text-slate-700">{prettify(entry.key)}</span>
                  <div className="h-2.5 rounded-full bg-slate-200">
                    <div className="h-2.5 rounded-full" style={{ width: `${widthPct}%`, backgroundColor: color }} />
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
  const title = `${config.yLabel || prettify(Array.isArray(config.y) ? config.y[0] : config.y)} by ${
    config.xLabel || prettify(config.x)
  }`;
  const chartLabel =
    config.type === "line" ? "line" : config.type === "stacked_bar" ? "stacked bar" : config.type.replace("_", " ");
  return (
    <section className="rounded-2xl border border-slate-200 bg-white/95 p-3 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">{title}</h3>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-slate-600">
          {chartLabel}
        </span>
      </div>
      {config.type === "line" || config.type === "stacked_bar" ? (
        <AreaChart table={table} config={config} />
      ) : (
        <BarChart table={table} config={config} />
      )}
    </section>
  );
}

function sortedRows(table: DataTable, tableConfig: TableConfig | null | undefined): Array<Record<string, DataCell>> {
  if (!tableConfig?.sortBy) return table.rows;
  const direction = tableConfig.sortDir === "asc" ? 1 : -1;
  return [...table.rows].sort((left, right) => direction * compareCells(left[tableConfig.sortBy ?? ""], right[tableConfig.sortBy ?? ""]));
}

function TablePanel({
  table,
  tableConfig,
  notice,
}: {
  table: DataTable;
  tableConfig: TableConfig | null | undefined;
  notice?: string;
}) {
  const columns = tableConfig?.columns?.length
    ? tableConfig.columns
    : table.columns.map((column) => ({
        key: column,
        label: prettify(column),
        format: "string" as const,
        align: "left" as const,
      }));
  const rows = useMemo(() => sortedRows(table, tableConfig), [table, tableConfig]);
  const showRank = Boolean(tableConfig?.showRank || tableConfig?.style === "ranked");
  return (
    <section className="rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">Primary Data Table</h3>
        {tableConfig?.style ? (
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
            {tableConfig.style}
          </span>
        ) : null}
      </div>
      {notice ? <p className="mt-2 text-xs font-medium text-amber-700">{notice}</p> : null}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[760px] border-separate border-spacing-y-1.5 text-left text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
              {showRank ? <th className="px-2 py-1 text-left">Rank</th> : null}
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
                {showRank ? (
                  <td className="rounded-l-xl px-2 py-2 text-left text-xs font-semibold text-slate-500">{rowIdx + 1}</td>
                ) : null}
                {columns.map((column, colIdx) => {
                  const isFirst = !showRank && colIdx === 0;
                  const isLast = colIdx === columns.length - 1;
                  return (
                    <td
                      key={`${rowIdx}-${column.key}`}
                      className={`px-2 py-2 text-sm ${column.align === "right" ? "text-right" : "text-left"} ${
                        isFirst ? "rounded-l-xl" : ""
                      } ${isLast ? "rounded-r-xl" : ""}`}
                    >
                      {formatCell(row[column.key] ?? null, column.format)}
                    </td>
                  );
                })}
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

  const readiness = chartConfig ? evaluateChartReadiness(table, chartConfig) : null;
  if (chartConfig && readiness?.ok) {
    return <ChartPanel table={table} config={chartConfig} />;
  }
  return <TablePanel table={table} tableConfig={tableConfig} notice={readiness && !readiness.ok ? readiness.reason : undefined} />;
}
