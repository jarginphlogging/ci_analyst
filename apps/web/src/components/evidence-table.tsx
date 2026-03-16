"use client";

import { useMemo } from "react";
import type { ChartConfig, ComparisonSignal, DataCell, DataTable, PrimaryVisual, TableConfig } from "../lib/types";

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

type ComparisonMode = NonNullable<TableConfig["comparisonMode"]>;
type DeltaPolicy = NonNullable<TableConfig["deltaPolicy"]>;

interface ResolvedComparisonConfig {
  labelKey: string;
  comparisonKeys: string[];
  baselineKey: string;
  mode: ComparisonMode;
  deltaPolicy: DeltaPolicy;
  threshold: number;
  overflow: boolean;
  columnByKey: Map<string, TableConfig["columns"][number]>;
}

const CHART_COLORS = ["#0284c7", "#ea580c", "#059669", "#dc2626", "#4338ca", "#0f766e"];
const ISO_DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function asNumber(value: DataCell | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function prettify(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function isComparisonLikeKey(column: string): boolean {
  const lowered = column.toLowerCase();
  if (/(19|20)\d{2}/.test(lowered)) return true;
  if (/\bq[1-4]\b/.test(lowered)) return true;
  return ["prior", "previous", "last_year", "last year", "current", "latest", "baseline", "index"].some((token) =>
    lowered.includes(token),
  );
}

function isTimeLike(value: DataCell | undefined): boolean {
  if (typeof value !== "string") return false;
  const raw = value.trim();
  if (!raw) return false;
  if (raw.length >= 10 && raw[4] === "-" && raw[7] === "-") return true;
  return Number.isFinite(Date.parse(raw));
}

function parseDateValue(value: string): Date | null {
  const raw = value.trim();
  if (!raw) return null;

  const dateOnlyMatch = raw.match(ISO_DATE_ONLY_PATTERN);
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

  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
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
    const parsed = parseDateValue(value);
    if (!parsed) return value;
    return parsed.toLocaleDateString();
  }
  return formatValue(asNumber(value), format);
}

function formatXLabel(value: string): string {
  if (!isTimeLike(value)) return value;
  const parsed = parseDateValue(value);
  if (!parsed) return value;
  const dateOnlyMatch = value.trim().match(ISO_DATE_ONLY_PATTERN);
  const day = dateOnlyMatch ? parsed.getDate() : parsed.getUTCDate();
  return parsed.toLocaleDateString(undefined, {
    month: "short",
    year: day === 1 ? "numeric" : undefined,
    day: day === 1 ? undefined : "numeric",
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
  if ((config.type === "line" || config.type === "stacked_area") && distinctX.size < 3) {
    return { ok: false, reason: "Chart downgraded to table: trend charts need at least 3 points." };
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
  const margin = { top: 8, right: 30, bottom: 34, left: 92 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const pointCount = Math.max(1, series[0]?.points.length ?? 1);
  const stacked = config.type === "stacked_area" && series.length > 1;
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
  const xTickIndexes =
    pointCount <= 8
      ? Array.from({ length: pointCount }, (_, idx) => idx)
      : Array.from({ length: 4 }, (_, idx) =>
          Math.round((idx * Math.max(0, pointCount - 1)) / 3),
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
              <text x={margin.left - 12} y={y + 4} textAnchor="end" fontSize="13" fill="#64748b">
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
          const isFirst = tickIdx === 0;
          const isLast = tickIdx === pointCount - 1;
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
              <text
                x={x}
                y={height - margin.bottom + 20}
                textAnchor={isFirst ? "start" : isLast ? "end" : "middle"}
                fontSize="13"
                fill="#64748b"
              >
                {formatXLabel(label)}
              </text>
            </g>
          );
        })}

        {series.map((entry, idx) => {
          const color = CHART_COLORS[idx % CHART_COLORS.length];
          const renderedPoints: ChartPoint[] = stacked
            ? entry.points.map((point, pointIdx) => ({
                x: point.x,
                y: stackedTopBySeries[idx]?.[pointIdx] ?? null,
              }))
            : entry.points;
          const path = linePath(renderedPoints, xOf, yOf);
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
              {renderedPoints.map((point, pointIdx) => {
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
                    <title>
                      {`${prettify(entry.key)} | ${formatXLabel(point.x)}: ${formatValue(
                        entry.points[pointIdx]?.y ?? null,
                        config.yFormat ?? "number",
                      )}`}
                    </title>
                  </circle>
                );
              })}
            </g>
          );
        })}

      </svg>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-slate-700">
        {series.map((entry, idx) => (
          <span
            key={entry.key}
            className={`inline-flex items-center gap-1.5 font-medium ${
              series.length === 1
                ? "rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-sm text-slate-700"
                : ""
            }`}
          >
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: CHART_COLORS[idx % CHART_COLORS.length] }} />
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
  const stacked = config.type === "stacked_bar" && series.length > 1;
  const stackedTotals = stacked
    ? xValues.map((_, idx) =>
        series.reduce((sum, entry) => {
          const value = entry.points[idx]?.y;
          return sum + (value !== null && Number.isFinite(value) ? Math.max(0, value) : 0);
        }, 0),
      )
    : [];
  const maxValue = Math.max(
    1,
    ...(stacked
      ? stackedTotals
      : series.flatMap((entry) => entry.points.map((point) => point.y).filter((value): value is number => value !== null))),
  );
  return (
    <div className="mt-3 space-y-3 rounded-2xl border border-slate-200 bg-white p-3">
      {xValues.map((x, idx) => (
        <div key={`${x}-${idx}`} className="rounded-xl border border-slate-200 bg-slate-50 p-2.5">
          <p className="text-xs font-semibold text-slate-700">{formatXLabel(x)}</p>
          {stacked ? (
            <div className="mt-1.5 space-y-2">
              <div className="relative h-3 overflow-hidden rounded-full bg-slate-200">
                {(() => {
                  let cumulative = 0;
                  return series.map((entry, seriesIdx) => {
                    const value = entry.points[idx]?.y;
                    const normalized = value !== null && Number.isFinite(value) ? Math.max(0, value) : 0;
                    const leftPct = (cumulative / maxValue) * 100;
                    const widthPct = (normalized / maxValue) * 100;
                    cumulative += normalized;
                    return (
                      <div
                        key={`${x}-${entry.key}`}
                        className="absolute bottom-0 top-0"
                        style={{
                          left: `${Math.max(0, Math.min(100, leftPct))}%`,
                          width: `${Math.max(0, Math.min(100, widthPct))}%`,
                          backgroundColor: CHART_COLORS[seriesIdx % CHART_COLORS.length],
                        }}
                        title={`${prettify(entry.key)}: ${formatValue(normalized, config.yFormat ?? "number")}`}
                      />
                    );
                  });
                })()}
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-2 text-xs">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  {series.map((entry, seriesIdx) => (
                    <span key={`${entry.key}-${seriesIdx}`} className="inline-flex items-center gap-1 text-slate-700">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: CHART_COLORS[seriesIdx % CHART_COLORS.length] }}
                      />
                      {prettify(entry.key)}
                    </span>
                  ))}
                </div>
                <span className="text-right font-semibold text-slate-700">
                  {formatValue(stackedTotals[idx] ?? 0, config.yFormat ?? "number")}
                </span>
              </div>
            </div>
          ) : (
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
          )}
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
    config.type === "line"
      ? "trend"
      : config.type === "stacked_bar"
      ? "stacked bar"
      : config.type === "stacked_area"
      ? "stacked area"
      : config.type.replace("_", " ");
  return (
    <section className="rounded-2xl border border-slate-200 bg-white/95 p-3 shadow-[0_5px_14px_rgba(14,44,68,0.06)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">{title}</h3>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-slate-600">
          {chartLabel}
        </span>
      </div>
      {config.type === "line" || config.type === "stacked_area" ? (
        <AreaChart table={table} config={config} />
      ) : (
        <BarChart table={table} config={config} />
      )}
    </section>
  );
}

function defaultColumnConfig(table: DataTable, column: string): TableConfig["columns"][number] {
  const kind = _columnKindForFormatting(table, column);
  return {
    key: column,
    label: prettify(column),
    format: kind,
    align: kind === "string" || kind === "date" ? "left" : "right",
  };
}

function _columnKindForFormatting(table: DataTable, column: string): TableConfig["columns"][number]["format"] {
  const values = table.rows.map((row) => row[column]).filter((value) => value !== null).slice(0, 200);
  if (!values.length) return "string";
  const numeric = values.filter((value) => asNumber(value) !== null).length;
  const dates = values.filter((value) => isTimeLike(value)).length;
  if (numeric / values.length >= 0.7) return "number";
  if (dates / values.length >= 0.7) return "date";
  return "string";
}

function effectiveColumns(table: DataTable, tableConfig: TableConfig | null | undefined): TableConfig["columns"] {
  if (tableConfig?.columns?.length) return tableConfig.columns;
  return table.columns.map((column) => defaultColumnConfig(table, column));
}

function resolveComparisonConfig(table: DataTable, tableConfig: TableConfig | null | undefined): ResolvedComparisonConfig | null {
  if (tableConfig?.style !== "comparison") return null;
  const columns = effectiveColumns(table, tableConfig);
  const columnByKey = new Map(columns.map((column) => [column.key, column]));
  const preferredLabel = columns.find((column) => column.format === "string" || column.format === "date");
  const fallbackLabel = table.columns.find((column) => columnByKey.get(column)?.format !== "number");
  const labelKey = preferredLabel?.key ?? fallbackLabel ?? table.columns[0];
  if (!labelKey) return null;

  const configKeys = (tableConfig.comparisonKeys ?? []).filter(
    (key, idx, arr) =>
      arr.indexOf(key) === idx &&
      table.columns.includes(key) &&
      isComparisonLikeKey(key) &&
      _columnKindForFormatting(table, key) !== "string" &&
      _columnKindForFormatting(table, key) !== "date",
  );
  const inferred = columns
    .filter(
      (column) =>
        column.key !== labelKey &&
        column.format !== "string" &&
        column.format !== "date" &&
        isComparisonLikeKey(column.key),
    )
    .map((column) => column.key);
  const comparisonKeys = (configKeys.length >= 2 ? configKeys : inferred).filter((key) => key !== labelKey);
  if (comparisonKeys.length < 2) return null;

  const mode: ComparisonMode = tableConfig.comparisonMode ?? "baseline";
  const baselineKey = comparisonKeys.includes(tableConfig.baselineKey ?? "") ? (tableConfig.baselineKey as string) : comparisonKeys[0];
  const deltaPolicy: DeltaPolicy = tableConfig.deltaPolicy ?? "both";
  const threshold = tableConfig.maxComparandsBeforeChartSwitch && tableConfig.maxComparandsBeforeChartSwitch > 0
    ? tableConfig.maxComparandsBeforeChartSwitch
    : 6;
  return {
    labelKey,
    comparisonKeys,
    baselineKey,
    mode,
    deltaPolicy,
    threshold,
    overflow: comparisonKeys.length > threshold,
    columnByKey,
  };
}

function ComparisonTablePanel({
  table,
  tableConfig,
  notice,
}: {
  table: DataTable;
  tableConfig: TableConfig | null | undefined;
  notice?: string;
}) {
  const config = resolveComparisonConfig(table, tableConfig);
  if (!config) {
    return (
      <TablePanel
        table={table}
        tableConfig={{
          ...(tableConfig ?? { style: "simple", columns: [] }),
          style: "simple",
        }}
        notice={notice ?? "Comparison config could not be validated. Showing raw table."}
      />
    );
  }

  const nonBaselineKeys = config.comparisonKeys.filter((key) => key !== config.baselineKey);
  const targetKey =
    config.mode === "pairwise"
      ? config.comparisonKeys[config.comparisonKeys.length - 1]
      : nonBaselineKeys[nonBaselineKeys.length - 1] ?? config.comparisonKeys[config.comparisonKeys.length - 1];
  const comparisonKey =
    config.mode === "pairwise"
      ? config.comparisonKeys[config.comparisonKeys.length - 2]
      : config.baselineKey;
  const topRows = table.rows
    .map((row, rowIdx) => {
      const label = String(row[config.labelKey] ?? `Row ${rowIdx + 1}`);
      const values = Object.fromEntries(config.comparisonKeys.map((key) => [key, asNumber(row[key])])) as Record<string, number | null>;
      const target = values[targetKey] ?? null;
      const baseline = values[comparisonKey] ?? null;
      const absDelta = target !== null && baseline !== null ? target - baseline : null;
      const pctDelta = absDelta !== null && baseline !== null && Math.abs(baseline) > Number.EPSILON ? (absDelta / baseline) * 100 : null;
      return {
        label,
        values,
        absDelta,
        pctDelta,
        impact: Math.abs(absDelta ?? 0),
      };
    })
    .sort((left, right) => right.impact - left.impact);
  const rows = config.overflow ? topRows.slice(0, 12) : topRows;
  const absLabel = `\u0394 ${prettify(targetKey)} vs ${prettify(comparisonKey)}`;
  const pctLabel = `%\u0394 ${prettify(targetKey)} vs ${prettify(comparisonKey)}`;
  const showAbs = config.deltaPolicy === "abs" || config.deltaPolicy === "both";
  const showPct = config.deltaPolicy === "pct" || config.deltaPolicy === "both";

  return (
    <section className="rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-[0_5px_14px_rgba(14,44,68,0.06)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">Comparison Table</h3>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
          {config.mode}
        </span>
      </div>
      {notice ? <p className="mt-2 text-xs font-medium text-amber-700">{notice}</p> : null}
      {config.overflow ? (
        <p className="mt-2 text-xs text-slate-600">
          Showing top movers only ({rows.length} rows). Full N-way raw output remains in Data Explorer.
        </p>
      ) : null}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[860px] border-separate border-spacing-y-1.5 text-left text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
              <th className="px-2 py-1 text-left">{config.columnByKey.get(config.labelKey)?.label ?? prettify(config.labelKey)}</th>
              {config.comparisonKeys.map((key) => (
                <th key={key} className="px-2 py-1 text-right">
                  {config.columnByKey.get(key)?.label ?? prettify(key)}
                </th>
              ))}
              {showAbs ? <th className="px-2 py-1 text-right">{absLabel}</th> : null}
              {showPct ? <th className="px-2 py-1 text-right">{pctLabel}</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIdx) => (
              <tr key={`${row.label}-${rowIdx}`} className="rounded-xl bg-slate-50 text-slate-800">
                <td className="rounded-l-xl px-2 py-2 text-left text-sm font-semibold text-slate-700">{row.label}</td>
                {config.comparisonKeys.map((key, colIdx) => (
                  <td
                    key={`${rowIdx}-${key}`}
                    className={`px-2 py-2 text-right text-sm ${
                      !showAbs && !showPct && colIdx === config.comparisonKeys.length - 1 ? "rounded-r-xl" : ""
                    }`}
                  >
                    {formatCell(row.values[key] ?? null, config.columnByKey.get(key)?.format ?? "number")}
                  </td>
                ))}
                {showAbs ? (
                  <td
                    className={`px-2 py-2 text-right text-sm font-semibold ${
                      row.absDelta !== null && row.absDelta >= 0 ? "text-emerald-700" : "text-rose-700"
                    } ${!showPct ? "rounded-r-xl" : ""}`}
                  >
                    {row.absDelta === null ? "-" : formatCell(row.absDelta, config.columnByKey.get(targetKey)?.format ?? "number")}
                  </td>
                ) : null}
                {showPct ? (
                  <td
                    className={`rounded-r-xl px-2 py-2 text-right text-sm font-semibold ${
                      row.pctDelta !== null && row.pctDelta >= 0 ? "text-emerald-700" : "text-rose-700"
                    }`}
                  >
                    {row.pctDelta === null ? "-" : formatValue(row.pctDelta, "percent")}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function metricFormat(metric: string): TableConfig["columns"][number]["format"] {
  const lowered = metric.toLowerCase();
  if (/(share|rate|ratio|pct|percent)/.test(lowered)) return "percent";
  if (/(sales|revenue|spend|cost|amount|avg|average|ticket)/.test(lowered)) return "currency";
  return "number";
}

function monthShort(month: number): string {
  return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][month] ?? "";
}

function compactPeriodLabel(value: string): string {
  const rangeMatch = value.match(/^(\d{4})-(\d{2})-(\d{2})\s+to\s+(\d{4})-(\d{2})-(\d{2})$/);
  if (!rangeMatch) return value;
  const startYear = Number(rangeMatch[1]);
  const startMonth = Number(rangeMatch[2]);
  const startDay = Number(rangeMatch[3]);
  const endYear = Number(rangeMatch[4]);
  const endMonth = Number(rangeMatch[5]);
  const endDay = Number(rangeMatch[6]);
  const quarterRanges: Record<number, [number, number, number, number]> = {
    1: [1, 1, 3, 31],
    2: [4, 1, 6, 30],
    3: [7, 1, 9, 30],
    4: [10, 1, 12, 31],
  };
  for (const [quarterText, [sMonth, sDay, eMonth, eDay]] of Object.entries(quarterRanges)) {
    if (startYear === endYear && startMonth === sMonth && startDay === sDay && endMonth === eMonth && endDay === eDay) {
      return `Q${quarterText} ${startYear}`;
    }
  }
  if (startYear === endYear) return `${monthShort(startMonth)}-${monthShort(endMonth)} ${startYear}`;
  return `${monthShort(startMonth)} ${startYear} - ${monthShort(endMonth)} ${endYear}`;
}

function formatSignedDelta(value: number, kind: TableConfig["columns"][number]["format"]): string {
  const sign = value >= 0 ? "+" : "-";
  const absolute = Math.abs(value);
  if (kind === "currency") {
    if (absolute >= 1_000_000_000) return `${sign}$${(absolute / 1_000_000_000).toFixed(1)}B`;
    if (absolute >= 1_000_000) return `${sign}$${(absolute / 1_000_000).toFixed(1)}M`;
    if (absolute >= 1_000) return `${sign}$${(absolute / 1_000).toFixed(1)}K`;
    return `${sign}${formatCell(absolute, "currency")}`;
  }
  if (kind === "number") {
    if (absolute >= 1_000_000_000) return `${sign}${(absolute / 1_000_000_000).toFixed(1)}B`;
    if (absolute >= 1_000_000) return `${sign}${(absolute / 1_000_000).toFixed(1)}M`;
    if (absolute >= 1_000) return `${sign}${(absolute / 1_000).toFixed(1)}K`;
    return `${sign}${formatCell(absolute, "number")}`;
  }
  return `${sign}${formatCell(absolute, kind)}`;
}

function metricOrderScore(metric: string): number {
  const lowered = metric.toLowerCase();
  if (/(sales|revenue|spend)/.test(lowered)) return 0;
  if (/transaction/.test(lowered)) return 1;
  if (/(avg|average|ticket|amount)/.test(lowered)) return 2;
  return 3;
}

function ComparisonSignalsPanel({
  comparisons,
}: {
  comparisons: ComparisonSignal[];
}) {
  const rows = [...comparisons]
    .sort((left, right) => {
      const leftMetricOrder = metricOrderScore(left.metric);
      const rightMetricOrder = metricOrderScore(right.metric);
      if (leftMetricOrder !== rightMetricOrder) return leftMetricOrder - rightMetricOrder;
      const leftRank = left.salienceRank ?? Number.MAX_SAFE_INTEGER;
      const rightRank = right.salienceRank ?? Number.MAX_SAFE_INTEGER;
      if (leftRank !== rightRank) return leftRank - rightRank;
      return Math.abs(right.absDelta) - Math.abs(left.absDelta);
    })
    .slice(0, 18);
  const primaryPrior = rows[0]?.priorPeriod?.trim();
  const primaryCurrent = rows[0]?.currentPeriod?.trim();
  const sameWindow = rows.every((row) => row.priorPeriod === primaryPrior && row.currentPeriod === primaryCurrent);
  const compactPrior = primaryPrior ? compactPeriodLabel(primaryPrior) : "";
  const compactCurrent = primaryCurrent ? compactPeriodLabel(primaryCurrent) : "";
  const title = sameWindow && compactPrior && compactCurrent ? `${compactCurrent} vs ${compactPrior}` : "Comparison Table";
  const priorValueHeader = sameWindow && compactPrior ? compactPrior : "Prior Value";
  const currentValueHeader = sameWindow && compactCurrent ? compactCurrent : "Current Value";
  const tableMinWidth = sameWindow ? "min-w-[760px]" : "min-w-[980px]";
  return (
    <section className="rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-[0_5px_14px_rgba(14,44,68,0.06)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">{title}</h3>
        {sameWindow && primaryPrior && primaryCurrent ? (
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
            comparison
          </span>
        ) : null}
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className={`w-full border-separate border-spacing-y-1.5 text-left text-sm ${tableMinWidth}`}>
          <thead>
            <tr className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
              <th className="px-2 py-1 text-left">Metric</th>
              {!sameWindow ? <th className="px-2 py-1 text-left">Prior Period</th> : null}
              <th className="px-2 py-1 text-right">{priorValueHeader}</th>
              {!sameWindow ? <th className="px-2 py-1 text-left">Current Period</th> : null}
              <th className="px-2 py-1 text-right">{currentValueHeader}</th>
              <th className="px-2 py-1 text-right">Delta</th>
              <th className="px-2 py-1 text-right">% Delta</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => {
              const valueFormat = metricFormat(row.metric);
              return (
                <tr key={`${row.id}-${idx}`} className="rounded-xl bg-slate-50 text-slate-800">
                  <td className="rounded-l-xl px-2 py-2 text-left text-sm font-semibold text-slate-700">{prettify(row.metric)}</td>
                  {!sameWindow ? <td className="px-2 py-2 text-left text-sm">{row.priorPeriod}</td> : null}
                  <td className="px-2 py-2 text-right text-sm">{formatCell(row.priorValue, valueFormat)}</td>
                  {!sameWindow ? <td className="px-2 py-2 text-left text-sm">{row.currentPeriod}</td> : null}
                  <td className="px-2 py-2 text-right text-sm">{formatCell(row.currentValue, valueFormat)}</td>
                  <td className={`px-2 py-2 text-right text-sm font-semibold ${row.absDelta >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                    {formatSignedDelta(row.absDelta, valueFormat)}
                  </td>
                  <td
                    className={`rounded-r-xl px-2 py-2 text-right text-sm font-semibold ${
                      (row.pctDelta ?? 0) >= 0 ? "text-emerald-700" : "text-rose-700"
                    }`}
                  >
                    {row.pctDelta === null || row.pctDelta === undefined ? "-" : formatValue(row.pctDelta, "percent")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
  const columns = effectiveColumns(table, tableConfig);
  const rows = useMemo(() => sortedRows(table, tableConfig), [table, tableConfig]);
  const showRank = Boolean(tableConfig?.showRank || tableConfig?.style === "ranked");
  return (
    <section className="rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-[0_5px_14px_rgba(14,44,68,0.06)]">
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
  comparisons,
}: {
  chartConfig?: ChartConfig | null;
  tableConfig?: TableConfig | null;
  primaryVisual?: PrimaryVisual;
  dataTables?: DataTable[];
  comparisons?: ComparisonSignal[];
}) {
  const table = dataTables?.[0];
  if (!table) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_5px_14px_rgba(14,44,68,0.06)]">
        <h3 className="text-sm font-semibold tracking-wide text-slate-900">{primaryVisual?.title?.trim() || "Visualization"}</h3>
        <p className="mt-2 text-sm text-slate-600">No tabular output was returned for this request.</p>
      </section>
    );
  }

  const readiness = chartConfig ? evaluateChartReadiness(table, chartConfig) : null;
  const semanticComparisonReady =
    (comparisons ?? []).length > 0 &&
    (tableConfig?.style === "comparison" || primaryVisual?.visualType === "comparison" || !chartConfig);
  if (semanticComparisonReady) {
    return <ComparisonSignalsPanel comparisons={comparisons ?? []} />;
  }
  const comparisonConfig = resolveComparisonConfig(table, tableConfig);
  const comparisonOverflow = Boolean(comparisonConfig?.overflow);
  if (chartConfig && readiness?.ok && !comparisonOverflow) {
    return <ChartPanel table={table} config={chartConfig} />;
  }
  if (tableConfig?.style === "comparison") {
    if ((comparisons ?? []).length > 0) {
      return <ComparisonSignalsPanel comparisons={comparisons ?? []} />;
    }
    return (
      <div className="space-y-3">
        {chartConfig && readiness?.ok && comparisonOverflow ? <ChartPanel table={table} config={chartConfig} /> : null}
        <ComparisonTablePanel
          table={table}
          tableConfig={tableConfig}
          notice={readiness && !readiness.ok ? readiness.reason : undefined}
        />
      </div>
    );
  }
  return <TablePanel table={table} tableConfig={tableConfig} notice={readiness && !readiness.ok ? readiness.reason : undefined} />;
}
