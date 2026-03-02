"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  AnalysisArtifact,
  AnalysisType,
  DataCell,
  DataTable,
  EvidenceRow,
  PresentationPlan,
  PrimaryVisual,
} from "@/lib/types";

type LegacySortKey = "segment" | "prior" | "current" | "changeBps" | "contribution";
type RankingSortKey = "rank" | "label" | "value" | "share";
type ComparisonSortKey = "label" | "prior" | "current" | "change";
type SortDirection = "asc" | "desc";
type VisualType = NonNullable<PrimaryVisual["visualType"]>;
type MetricFormatKind = "currency" | "percent" | "count" | "number";

const ANALYSIS_VISUAL_POLICY: Record<AnalysisType, VisualType> = {
  trend_over_time: "trend",
  ranking_top_n_bottom_n: "ranking",
  comparison: "comparison",
  composition_breakdown: "ranking",
  aggregation_summary_stats: "snapshot",
  point_in_time_snapshot: "snapshot",
  period_over_period_change: "comparison",
  anomaly_outlier_detection: "trend",
  drill_down_root_cause: "comparison",
  correlation_relationship: "comparison",
  cohort_analysis: "trend",
  distribution_histogram: "distribution",
  forecasting_projection: "trend",
  threshold_filter_segmentation: "table",
  cumulative_running_total: "trend",
  rate_ratio_efficiency: "comparison",
};

const legacySortOptions: { key: LegacySortKey; label: string }[] = [
  { key: "contribution", label: "Contribution" },
  { key: "changeBps", label: "Change" },
  { key: "current", label: "Current" },
  { key: "segment", label: "Segment" },
];

const rankingSortOptions: { key: RankingSortKey; label: string }[] = [
  { key: "value", label: "Value" },
  { key: "share", label: "Share" },
  { key: "rank", label: "Rank" },
  { key: "label", label: "Label" },
];

const comparisonSortOptions: { key: ComparisonSortKey; label: string }[] = [
  { key: "change", label: "Change" },
  { key: "current", label: "Current" },
  { key: "prior", label: "Prior" },
  { key: "label", label: "Label" },
];

const moduleSectionClass =
  "rounded-3xl border border-slate-200/90 bg-[linear-gradient(160deg,rgba(255,255,255,0.96),rgba(245,250,255,0.9))] p-4 shadow-[0_14px_34px_rgba(14,44,68,0.10)] animate-fade-up";
const tableContainerClass = "mt-3 overflow-x-auto rounded-2xl border border-slate-200/80 bg-white/70 p-2";
const tableClass = "w-full min-w-[640px] border-separate border-spacing-y-1.5 text-left text-sm";
const tableHeadClass = "text-[11px] uppercase tracking-[0.14em] text-slate-500";
const tableRowClass =
  "rounded-xl bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(248,251,255,0.96))] text-slate-800 shadow-[inset_0_0_0_1px_rgba(203,213,225,0.55)] transition-colors hover:bg-white";

function semanticRoleLabel(bindingName: string): string {
  if (bindingName === "left_value") return "baseline";
  if (bindingName === "right_value") return "comparison";
  if (bindingName === "delta_value") return "delta";
  if (bindingName === "delta_pct") return "delta %";
  if (bindingName === "value") return "measure";
  if (bindingName === "rank_index") return "rank";
  return prettifyColumn(bindingName);
}

function resolveUniqueLabels(
  entries: Array<{ id: string; label: string; semantic: string }>,
): Record<string, string> {
  const counts = new Map<string, number>();
  entries.forEach((entry) => {
    const key = entry.label.toLowerCase();
    counts.set(key, (counts.get(key) ?? 0) + 1);
  });
  return entries.reduce<Record<string, string>>((accumulator, entry) => {
    const isDuplicate = (counts.get(entry.label.toLowerCase()) ?? 0) > 1;
    accumulator[entry.id] = isDuplicate ? `${entry.label} (${entry.semantic})` : entry.label;
    return accumulator;
  }, {});
}

function inferredFormatKind(
  key: string,
  options?: { hints?: string[]; samples?: Array<number | null> },
): MetricFormatKind {
  const text = [key, ...(options?.hints ?? [])].join(" ").toLowerCase();
  const values = (options?.samples ?? []).filter((value): value is number => value !== null && Number.isFinite(value));
  const maxAbs = values.length ? Math.max(...values.map((value) => Math.abs(value))) : 0;

  if (/(pct|percent|percentage|share|ratio|rate|mix|conversion|utilization)/i.test(text)) {
    return "percent";
  }
  if (/(sales|revenue|amount|spend|cost|profit|income|gmv|dollar|usd|\$)/i.test(text)) {
    return "currency";
  }
  if (/(count|transactions|txn|orders|volume|units|visits|customers|stores|records|rows)/i.test(text)) {
    return "count";
  }
  if (values.length > 0 && maxAbs <= 1 && values.some((value) => !Number.isInteger(value))) {
    return "percent";
  }
  return "number";
}

function asNumber(value: DataCell | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function prettifyColumn(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function directionSymbol(direction: SortDirection): string {
  return direction === "asc" ? "↑" : "↓";
}

function defaultDirection(sortBy: RankingSortKey | ComparisonSortKey): SortDirection {
  if (sortBy === "label" || sortBy === "rank") return "asc";
  return "desc";
}

function formatValue(
  value: number | null,
  key: string,
  options?: { hints?: string[]; samples?: Array<number | null> },
): string {
  if (value === null) return "-";
  const kind = inferredFormatKind(key, options);
  if (kind === "percent") {
    const normalized = Math.abs(value) <= 1 ? value * 100 : value;
    return `${normalized.toFixed(Math.abs(normalized) >= 10 ? 1 : 2)}%`;
  }
  if (kind === "currency") {
    return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  }
  if (kind === "count") {
    return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  if (Math.abs(value) >= 1000 && Math.abs(value % 1) < 0.00001) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatCell(value: DataCell): string {
  if (value === null) return "-";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  return value;
}

function formatCellForColumn(column: string, value: DataCell): string {
  if (value === null) return "-";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return formatValue(value, column);
  if (typeof value === "string") {
    const numeric = asNumber(value);
    if (numeric !== null) return formatValue(numeric, column);
    return value;
  }
  return formatCell(value);
}

function formatMonthLabel(value: DataCell): string {
  if (value === null) return "-";
  const raw = String(value).trim();
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (dateOnly) {
    const year = Number(dateOnly[1]);
    const monthIndex = Number(dateOnly[2]) - 1;
    const day = Number(dateOnly[3]);
    const utcDate = new Date(Date.UTC(year, monthIndex, day));
    return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric", timeZone: "UTC" }).format(utcDate);
  }
  const parsed = Date.parse(raw);
  if (!Number.isFinite(parsed)) return raw;
  return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(new Date(parsed));
}

function parseTime(value: DataCell | undefined): number {
  if (!value) return Number.POSITIVE_INFINITY;
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

function resolvePlanBinding(
  row: Record<string, DataCell>,
  plan: PresentationPlan,
  bindingName: string,
  rowIndex = 0,
): DataCell {
  const ref = plan.bindings[bindingName];
  if (!ref) return null;
  if (ref === "__row_index__") {
    return rowIndex + 1;
  }
  if (ref.startsWith("const:")) {
    return ref.slice(6);
  }
  return row[ref] ?? null;
}

function bindingFormatKey(plan: PresentationPlan, bindingName: string, fallback: string): string {
  const ref = plan.bindings[bindingName];
  if (!ref || ref === "__row_index__" || ref.startsWith("const:")) {
    return fallback;
  }
  return ref;
}

function bindingHeaderLabel(plan: PresentationPlan, bindingName: string, fallback: string): string {
  return prettifyColumn(bindingFormatKey(plan, bindingName, fallback));
}

function comparePlanValues(a: DataCell, b: DataCell): number {
  const aNumber = asNumber(a);
  const bNumber = asNumber(b);
  if (aNumber !== null && bNumber !== null) {
    return aNumber - bNumber;
  }
  const aTime = parseTime(a);
  const bTime = parseTime(b);
  if (Number.isFinite(aTime) && Number.isFinite(bTime)) {
    return aTime - bTime;
  }
  return String(a ?? "").localeCompare(String(b ?? ""));
}

function sortRowsByPlan(rows: Array<Record<string, DataCell>>, plan: PresentationPlan): Array<Record<string, DataCell>> {
  if (!plan.sort?.length) return rows;
  const sortRules = plan.sort
    .map((entry) => {
      const [bindingName, direction] = entry.split(":");
      if (!bindingName || !direction) return null;
      if (direction !== "asc" && direction !== "desc") return null;
      return { bindingName, direction };
    })
    .filter((item): item is { bindingName: string; direction: "asc" | "desc" } => item !== null);

  if (!sortRules.length) return rows;

  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      for (const rule of sortRules) {
        const leftValue = resolvePlanBinding(left.row, plan, rule.bindingName, left.index);
        const rightValue = resolvePlanBinding(right.row, plan, rule.bindingName, right.index);
        const comparison = comparePlanValues(leftValue, rightValue);
        if (comparison !== 0) {
          return rule.direction === "asc" ? comparison : -comparison;
        }
      }
      return 0;
    })
    .map((item) => item.row);
}

function deltaColorClass(value: number | null): string {
  if (value === null || value === 0) return "text-slate-600";
  return value > 0 ? "text-emerald-700" : "text-rose-700";
}

function Sparkline({
  values,
  xLabels,
  valueFormatKey = "value",
  contextHints = [],
}: {
  values: number[];
  xLabels?: string[];
  valueFormatKey?: string;
  contextHints?: string[];
}) {
  if (values.length < 2) return null;
  const width = 760;
  const height = 160;
  const paddingX = 16;
  const paddingY = 14;
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = maxValue - minValue || 1;
  const step = (width - paddingX * 2) / Math.max(1, values.length - 1);

  const points = values.map((value, index) => {
    const x = paddingX + step * index;
    const y = paddingY + ((maxValue - value) / range) * (height - paddingY * 2);
    return { x, y };
  });

  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");
  const baselineY = height - paddingY;
  const areaPath = `M ${points[0]?.x ?? 0} ${baselineY} L ${polyline} L ${points[points.length - 1]?.x ?? width} ${baselineY} Z`;
  const spread = maxValue - minValue;
  const firstLabel = xLabels?.[0] ?? "Start";
  const lastLabel = xLabels?.[xLabels.length - 1] ?? "End";

  return (
    <div className="mt-3 rounded-2xl border border-slate-200/80 bg-[linear-gradient(180deg,rgba(249,252,255,0.95),rgba(240,246,252,0.9))] px-3 py-3">
      <div className="mb-2 grid grid-cols-3 gap-2 text-[11px] text-slate-600">
        <div className="rounded-md bg-white/70 px-2 py-1">
          <span className="font-semibold text-slate-700">Low:</span>{" "}
          {formatValue(minValue, valueFormatKey, { hints: contextHints, samples: values })}
        </div>
        <div className="rounded-md bg-white/70 px-2 py-1 text-center">
          <span className="font-semibold text-slate-700">High:</span>{" "}
          {formatValue(maxValue, valueFormatKey, { hints: contextHints, samples: values })}
        </div>
        <div className="rounded-md bg-white/70 px-2 py-1 text-right">
          <span className="font-semibold text-slate-700">Spread:</span>{" "}
          {formatValue(spread, valueFormatKey, { hints: contextHints, samples: values })}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-36 w-full" role="img" aria-label="Trend line chart">
        <defs>
          <linearGradient id="sparkline-stroke" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#0284c7" />
            <stop offset="100%" stopColor="#0d9488" />
          </linearGradient>
          <linearGradient id="sparkline-area" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(14,165,233,0.30)" />
            <stop offset="100%" stopColor="rgba(14,165,233,0.02)" />
          </linearGradient>
        </defs>
        <line x1={paddingX} y1={baselineY} x2={width - paddingX} y2={baselineY} stroke="#cbd5e1" strokeWidth="1" />
        <path d={areaPath} fill="url(#sparkline-area)" />
        <polyline fill="none" stroke="url(#sparkline-stroke)" strokeWidth="3.25" strokeLinejoin="round" strokeLinecap="round" points={polyline} />
        {points.map((point, index) => (
          <circle
            key={index}
            cx={point.x}
            cy={point.y}
            r={index === points.length - 1 ? 4.2 : 2.6}
            fill={index === points.length - 1 ? "#0f766e" : "#0284c7"}
          />
        ))}
        <text x={paddingX} y={height - 2} fontSize="11" fill="#64748b">
          {firstLabel}
        </text>
        <text x={width - paddingX} y={height - 2} textAnchor="end" fontSize="11" fill="#64748b">
          {lastLabel}
        </text>
      </svg>
    </div>
  );
}

function artifactLabel(kind: AnalysisArtifact["kind"]): string {
  if (kind === "ranking_breakdown") return "Ranking";
  if (kind === "comparison_breakdown" || kind === "delta_breakdown") return "Comparison";
  if (kind === "trend_breakdown") return "Trend";
  if (kind === "distribution_breakdown") return "Distribution";
  return "Module";
}

function artifactDescription(artifact: AnalysisArtifact): string {
  if (artifact.kind === "ranking_breakdown") {
    return "Ranked distribution computed from retrieved SQL output. Shows share by entity.";
  }
  return artifact.description ?? "Adaptive analysis module from retrieved SQL output.";
}

function isArtifactFinished(artifact: AnalysisArtifact): boolean {
  if (!artifact.rows.length) return false;
  if (artifact.kind === "trend_breakdown") return artifact.rows.length >= 2;
  return true;
}

function artifactKindsForVisualType(visualType: VisualType): AnalysisArtifact["kind"][] {
  if (visualType === "trend") return ["trend_breakdown"];
  if (visualType === "ranking") return ["ranking_breakdown"];
  if (visualType === "comparison") return ["comparison_breakdown", "delta_breakdown"];
  if (visualType === "distribution") return ["distribution_breakdown"];
  return [];
}

function resolveVisualType({
  analysisType,
  primaryVisual,
  artifacts,
  dataTables,
}: {
  analysisType?: AnalysisType;
  primaryVisual?: PrimaryVisual;
  artifacts: AnalysisArtifact[];
  dataTables?: DataTable[];
}): VisualType {
  const intended = analysisType ? ANALYSIS_VISUAL_POLICY[analysisType] : primaryVisual?.visualType;
  const requested: VisualType = intended ?? primaryVisual?.visualType ?? "snapshot";
  if (requested === "snapshot" || requested === "table") return requested;

  const allowedKinds = new Set(artifactKindsForVisualType(requested));
  const hasCompatibleArtifact = artifacts.some((artifact) => allowedKinds.has(artifact.kind) && isArtifactFinished(artifact));
  if (hasCompatibleArtifact) return requested;
  if ((dataTables?.length ?? 0) > 0) return "table";
  return "snapshot";
}

function contributionWidth(value: number): number {
  return Math.max(8, Math.min(100, Math.round(value * 140)));
}

function RankingModule({ artifact }: { artifact: AnalysisArtifact }) {
  const [sortBy, setSortBy] = useState<RankingSortKey>("value");
  const [direction, setDirection] = useState<SortDirection>("desc");

  const excluded = new Set(["rank", "share_pct", "cumulative_share_pct"]);
  const dimensionKey = artifact.dimensionKey ?? artifact.columns.find((column) => !excluded.has(column)) ?? "dimension";
  const valueKey =
    artifact.valueKey ?? artifact.columns.find((column) => !excluded.has(column) && column !== dimensionKey) ?? "value";

  const parsedRows = useMemo(
    () =>
      artifact.rows.map((row, index) => ({
        rank: asNumber(row.rank) ?? index + 1,
        label: String(row[dimensionKey] ?? `Item ${index + 1}`),
        value: asNumber(row[valueKey]) ?? 0,
        share: asNumber(row.share_pct) ?? 0,
      })),
    [artifact.rows, dimensionKey, valueKey],
  );

  const sortedRows = useMemo(() => {
    const multiplier = direction === "asc" ? 1 : -1;
    return [...parsedRows].sort((a, b) => {
      if (sortBy === "rank") return multiplier * (a.rank - b.rank);
      if (sortBy === "label") return multiplier * a.label.localeCompare(b.label);
      if (sortBy === "share") return multiplier * (a.share - b.share);
      return multiplier * (a.value - b.value);
    });
  }, [parsedRows, sortBy, direction]);

  const maxShare = useMemo(() => Math.max(0, ...parsedRows.map((row) => row.share)), [parsedRows]);
  const valueHints = [artifact.title, artifact.description ?? "", valueKey];

  return (
    <>
      <div className="mt-3 inline-flex items-center rounded-full bg-slate-100 p-1">
        {rankingSortOptions.map((option) => (
          <button
            key={option.key}
            onClick={() => {
              if (option.key === sortBy) {
                setDirection((prev) => (prev === "asc" ? "desc" : "asc"));
                return;
              }
              setSortBy(option.key);
              setDirection(defaultDirection(option.key));
            }}
            className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${
              sortBy === option.key ? "bg-white text-slate-900 shadow" : "text-slate-600 hover:text-slate-900"
            }`}
            type="button"
          >
            {option.label}
            {sortBy === option.key ? ` ${directionSymbol(direction)}` : ""}
          </button>
        ))}
      </div>

      <div className={tableContainerClass}>
        <table className={tableClass}>
          <thead>
            <tr className={tableHeadClass}>
              <th className="px-2 py-1">Rank</th>
              <th className="px-2 py-1">{prettifyColumn(dimensionKey)}</th>
              <th className="px-2 py-1">{prettifyColumn(valueKey)}</th>
              <th className="px-2 py-1">Share</th>
              <th className="px-2 py-1">Distribution</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <tr key={`${row.rank}-${row.label}`} className={tableRowClass}>
                <td className="rounded-l-xl px-2 py-2 font-medium">{row.rank}</td>
                <td className="px-2 py-2 font-medium">{row.label}</td>
                <td className="px-2 py-2">{formatValue(row.value, valueKey, { hints: valueHints, samples: parsedRows.map((entry) => entry.value) })}</td>
                <td className="px-2 py-2">{row.share.toFixed(2)}%</td>
                <td className="rounded-r-xl px-2 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 w-32 rounded-full bg-slate-200/80">
                      <div
                        className="h-2.5 rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-200"
                        style={{ width: `${maxShare > 0 ? Math.min(100, Math.max(0, (row.share / maxShare) * 100)) : 0}%` }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-slate-700">{row.share.toFixed(1)}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ComparisonModule({ artifact }: { artifact: AnalysisArtifact }) {
  const [sortBy, setSortBy] = useState<ComparisonSortKey>("change");
  const [direction, setDirection] = useState<SortDirection>("desc");

  const dimensionKey = artifact.dimensionKey ?? artifact.columns[0] ?? "dimension";

  const parsedRows = useMemo(
    () =>
      artifact.rows.map((row, index) => ({
        label: String(row[dimensionKey] ?? `Row ${index + 1}`),
        prior: asNumber(row.prior_value),
        current: asNumber(row.current_value),
        change: asNumber(row.change_value),
        changePct: asNumber(row.change_pct),
      })),
    [artifact.rows, dimensionKey],
  );

  const sortedRows = useMemo(() => {
    const multiplier = direction === "asc" ? 1 : -1;
    return [...parsedRows].sort((a, b) => {
      if (sortBy === "label") return multiplier * a.label.localeCompare(b.label);
      if (sortBy === "prior") return multiplier * ((a.prior ?? 0) - (b.prior ?? 0));
      if (sortBy === "current") return multiplier * ((a.current ?? 0) - (b.current ?? 0));
      return multiplier * ((a.change ?? 0) - (b.change ?? 0));
    });
  }, [parsedRows, sortBy, direction]);
  const valueHints = [artifact.title, artifact.description ?? "", artifact.dimensionKey ?? ""];
  const priorSamples = parsedRows.map((row) => row.prior);
  const currentSamples = parsedRows.map((row) => row.current);
  const changeSamples = parsedRows.map((row) => row.change);

  return (
    <>
      <div className="mt-3 inline-flex items-center rounded-full bg-slate-100 p-1">
        {comparisonSortOptions.map((option) => (
          <button
            key={option.key}
            onClick={() => {
              if (option.key === sortBy) {
                setDirection((prev) => (prev === "asc" ? "desc" : "asc"));
                return;
              }
              setSortBy(option.key);
              setDirection(defaultDirection(option.key));
            }}
            className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${
              sortBy === option.key ? "bg-white text-slate-900 shadow" : "text-slate-600 hover:text-slate-900"
            }`}
            type="button"
          >
            {option.label}
            {sortBy === option.key ? ` ${directionSymbol(direction)}` : ""}
          </button>
        ))}
      </div>

      <div className={tableContainerClass}>
        <table className={tableClass}>
          <thead>
            <tr className={tableHeadClass}>
              <th className="px-2 py-1">{prettifyColumn(dimensionKey)}</th>
              <th className="px-2 py-1">Prior</th>
              <th className="px-2 py-1">Current</th>
              <th className="px-2 py-1">Change</th>
              <th className="px-2 py-1">Change %</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <tr key={row.label} className={tableRowClass}>
                <td className="rounded-l-xl px-2 py-2 font-medium">{row.label}</td>
                <td className="px-2 py-2">{formatValue(row.prior, "prior", { hints: valueHints, samples: priorSamples })}</td>
                <td className="px-2 py-2">{formatValue(row.current, "current", { hints: valueHints, samples: currentSamples })}</td>
                <td className={`px-2 py-2 font-semibold ${deltaColorClass(row.change)}`}>
                  {formatValue(row.change, "change", { hints: valueHints, samples: changeSamples })}
                </td>
                <td className="rounded-r-xl px-2 py-2">{row.changePct === null ? "-" : `${row.changePct.toFixed(2)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function TrendModule({ artifact }: { artifact: AnalysisArtifact }) {
  const timeKey = artifact.timeKey ?? artifact.columns[0] ?? "period";
  const valueKey = artifact.valueKey ?? artifact.columns[1] ?? "value";

  const trendRows = useMemo(() => {
    const ordered = [...artifact.rows].sort((a, b) => parseTime(a[timeKey]) - parseTime(b[timeKey]));
    return ordered.map((row, index) => {
      const value = asNumber(row[valueKey]) ?? 0;
      const prevValue = index > 0 ? asNumber(ordered[index - 1][valueKey]) : null;
      const parsedDelta = asNumber(row.period_change);
      const delta = parsedDelta ?? (prevValue === null ? null : value - prevValue);
      const deltaPct = delta === null || prevValue === null || prevValue === 0 ? null : (delta / prevValue) * 100;
      return {
        period: row[timeKey] ?? null,
        value,
        delta,
        deltaPct,
      };
    });
  }, [artifact.rows, timeKey, valueKey]);

  const firstValue = trendRows[0]?.value ?? null;
  const lastValue = trendRows[trendRows.length - 1]?.value ?? null;
  const netDelta = firstValue !== null && lastValue !== null ? lastValue - firstValue : null;
  const netDeltaPct = firstValue && netDelta !== null ? (netDelta / firstValue) * 100 : null;
  const strongestGain = trendRows.reduce<{ delta: number; period: DataCell } | null>((best, row) => {
    if (row.delta === null || row.delta <= 0) return best;
    if (!best || row.delta > best.delta) return { delta: row.delta, period: row.period };
    return best;
  }, null);
  const strongestDrop = trendRows.reduce<{ delta: number; period: DataCell } | null>((best, row) => {
    if (row.delta === null || row.delta >= 0) return best;
    if (!best || row.delta < best.delta) return { delta: row.delta, period: row.period };
    return best;
  }, null);
  const trendHints = [artifact.title, artifact.description ?? "", valueKey];
  const valueSamples = trendRows.map((row) => row.value);
  const deltaSamples = trendRows.map((row) => row.delta);

  return (
    <>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Net Change</p>
          <p className={`mt-1.5 text-sm font-semibold ${deltaColorClass(netDelta)}`}>
            {netDelta === null ? "-" : formatValue(netDelta, valueKey, { hints: trendHints, samples: deltaSamples })}
          </p>
          <p className="mt-1 text-xs text-slate-600">{netDeltaPct === null ? "-" : `${netDeltaPct.toFixed(2)}%`}</p>
        </article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Strongest Increase</p>
          <p className="mt-1.5 text-sm font-semibold text-emerald-700">
            {strongestGain ? formatValue(strongestGain.delta, valueKey, { hints: trendHints, samples: deltaSamples }) : "-"}
          </p>
          <p className="mt-1 text-xs text-slate-600">{strongestGain ? formatMonthLabel(strongestGain.period) : "-"}</p>
        </article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Strongest Decline</p>
          <p className="mt-1.5 text-sm font-semibold text-rose-700">
            {strongestDrop ? formatValue(strongestDrop.delta, valueKey, { hints: trendHints, samples: deltaSamples }) : "-"}
          </p>
          <p className="mt-1 text-xs text-slate-600">{strongestDrop ? formatMonthLabel(strongestDrop.period) : "-"}</p>
        </article>
      </div>

      <Sparkline
        values={trendRows.map((row) => row.value)}
        xLabels={trendRows.map((row) => formatMonthLabel(row.period))}
        valueFormatKey={valueKey}
        contextHints={trendHints}
      />

      <div className={tableContainerClass}>
        <table className={tableClass}>
          <thead>
            <tr className={tableHeadClass}>
              <th className="px-2 py-1">{prettifyColumn(timeKey)}</th>
              <th className="px-2 py-1">{prettifyColumn(valueKey)}</th>
              <th className="px-2 py-1">Change vs Previous</th>
              <th className="px-2 py-1">Change %</th>
            </tr>
          </thead>
          <tbody>
            {trendRows.map((row, index) => (
              <tr key={`${String(row.period)}-${index}`} className={tableRowClass}>
                <td className="rounded-l-xl px-2 py-2 font-medium">{formatMonthLabel(row.period)}</td>
                <td className="px-2 py-2">{formatValue(row.value, valueKey, { hints: trendHints, samples: valueSamples })}</td>
                <td className={`px-2 py-2 font-semibold ${deltaColorClass(row.delta)}`}>
                  {row.delta === null ? "-" : formatValue(row.delta, valueKey, { hints: trendHints, samples: deltaSamples })}
                </td>
                <td className={`rounded-r-xl px-2 py-2 font-semibold ${deltaColorClass(row.delta)}`}>
                  {row.deltaPct === null ? "-" : `${row.deltaPct.toFixed(2)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DistributionModule({ artifact }: { artifact: AnalysisArtifact }) {
  const valueHints = [artifact.title, artifact.description ?? "", artifact.valueKey ?? "value"];
  const valueSamples = artifact.rows.map((row) => asNumber(row.value));
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {artifact.rows.map((row, index) => (
        <article
          key={`${String(row.stat)}-${index}`}
          className="rounded-xl border border-slate-200/90 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(246,250,255,0.95))] p-3 shadow-[inset_0_0_0_1px_rgba(226,232,240,0.45)]"
        >
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{String(row.stat ?? "stat")}</p>
          <p className="mt-1.5 text-sm font-semibold text-slate-900">
            {formatValue(asNumber(row.value), artifact.valueKey ?? "value", { hints: valueHints, samples: valueSamples })}
          </p>
          {row.label ? <p className="mt-1 text-xs text-slate-600">{String(row.label)}</p> : null}
        </article>
      ))}
    </div>
  );
}

function GenericModule({ artifact }: { artifact: AnalysisArtifact }) {
  return (
    <div className={tableContainerClass}>
      <table className={tableClass}>
        <thead>
          <tr className={tableHeadClass}>
            {artifact.columns.map((column) => (
              <th key={column} className="px-2 py-1">
                {prettifyColumn(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {artifact.rows.map((row, index) => (
            <tr key={`${artifact.id}-${index}`} className={tableRowClass}>
              {artifact.columns.map((column, colIndex) => (
                <td
                  key={`${artifact.id}-${index}-${column}`}
                  className={`px-2 py-2 ${colIndex === 0 ? "rounded-l-xl font-medium" : ""} ${
                    colIndex === artifact.columns.length - 1 ? "rounded-r-xl" : ""
                  }`}
                >
                  {formatCellForColumn(column, row[column] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SnapshotModule({ table }: { table: DataTable }) {
  const row = table.rows[0] ?? {};
  const entries = table.columns
    .map((column) => ({ column, value: row[column] ?? null }))
    .filter((entry) => entry.value !== null)
    .slice(0, 8);

  if (entries.length === 0) {
    return <p className="mt-3 text-sm text-slate-600">No snapshot rows were returned for this request.</p>;
  }

  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map((entry) => (
        <article
          key={entry.column}
          className="rounded-xl border border-slate-200/90 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(246,250,255,0.95))] p-3 shadow-[inset_0_0_0_1px_rgba(226,232,240,0.45)]"
        >
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{prettifyColumn(entry.column)}</p>
          <p className="mt-1.5 text-sm font-semibold text-slate-900">{formatCellForColumn(entry.column, entry.value)}</p>
        </article>
      ))}
    </div>
  );
}

function SnapshotArtifactModule({ artifact }: { artifact: AnalysisArtifact }) {
  const row = artifact.rows[0] ?? {};
  const entries = artifact.columns
    .map((column) => ({ column, value: row[column] ?? null }))
    .filter((entry) => entry.value !== null)
    .slice(0, 8);

  if (entries.length === 0) {
    return <p className="mt-3 text-sm text-slate-600">No snapshot rows were returned for this request.</p>;
  }

  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map((entry) => (
        <article
          key={entry.column}
          className="rounded-xl border border-slate-200/90 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(246,250,255,0.95))] p-3 shadow-[inset_0_0_0_1px_rgba(226,232,240,0.45)]"
        >
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{prettifyColumn(entry.column)}</p>
          <p className="mt-1.5 text-sm font-semibold text-slate-900">{formatCellForColumn(entry.column, entry.value)}</p>
        </article>
      ))}
    </div>
  );
}

function TableModule({ table }: { table: DataTable }) {
  const limitedRows = table.rows.slice(0, 20);
  return (
    <div className={tableContainerClass}>
      <table className={tableClass}>
        <thead>
          <tr className={tableHeadClass}>
            {table.columns.map((column) => (
              <th key={column} className="px-2 py-1">
                {prettifyColumn(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {limitedRows.map((row, index) => (
            <tr key={`${table.id}-${index}`} className={tableRowClass}>
              {table.columns.map((column, colIndex) => (
                <td
                  key={`${table.id}-${index}-${column}`}
                  className={`px-2 py-2 ${colIndex === 0 ? "rounded-l-xl font-medium" : ""} ${
                    colIndex === table.columns.length - 1 ? "rounded-r-xl" : ""
                  }`}
                >
                  {formatCellForColumn(column, row[column] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {table.rowCount > limitedRows.length ? (
        <p className="mt-2 text-xs text-slate-600">Showing first {limitedRows.length} of {table.rowCount} rows.</p>
      ) : null}
    </div>
  );
}

function PlanRankingModule({ plan, table }: { plan: PresentationPlan; table: DataTable }) {
  const groupHeader = bindingHeaderLabel(plan, "group_label", "group");
  const rankHeader = bindingHeaderLabel(plan, "rank_index", "rank");
  const entityHeader = bindingHeaderLabel(plan, "entity_label", "entity");
  const valueFormat = bindingFormatKey(plan, "value", "value");
  const valueHeader = bindingHeaderLabel(plan, "value", semanticRoleLabel("value"));
  const shareHeader = bindingHeaderLabel(plan, "share_of_scope", "share_pct");
  const parsedRows = useMemo(() => {
    const sorted = sortRowsByPlan(table.rows, plan);
    return sorted.map((row, index) => ({
      group: String(resolvePlanBinding(row, plan, "group_label", index) ?? "All"),
      rank: asNumber(resolvePlanBinding(row, plan, "rank_index", index)) ?? index + 1,
      label: String(resolvePlanBinding(row, plan, "entity_label", index) ?? `Entity ${index + 1}`),
      value: asNumber(resolvePlanBinding(row, plan, "value", index)),
      share: asNumber(resolvePlanBinding(row, plan, "share_of_scope", index)),
    }));
  }, [plan, table.rows]);

  const hasShare = parsedRows.some((row) => row.share !== null);
  const maxShare = useMemo(
    () =>
      Math.max(
        0,
        ...parsedRows
          .map((row) => row.share)
          .filter((value): value is number => value !== null),
      ),
    [parsedRows],
  );
  const showGroup = useMemo(() => {
    const groups = new Set(parsedRows.map((row) => row.group));
    return groups.size > 1;
  }, [parsedRows]);
  const valueHints = [plan.title, plan.scopeLabel, valueHeader];
  const valueSamples = parsedRows.map((row) => row.value);

  return (
    <div className={tableContainerClass}>
      <table className="w-full min-w-[680px] border-separate border-spacing-y-1.5 text-left text-sm">
        <thead>
          <tr className={tableHeadClass}>
            {showGroup ? <th className="px-2 py-1">{groupHeader}</th> : null}
            <th className="px-2 py-1">{rankHeader}</th>
            <th className="px-2 py-1">{entityHeader}</th>
            <th className="px-2 py-1">{valueHeader}</th>
            {hasShare ? <th className="px-2 py-1">{shareHeader}</th> : null}
            {hasShare ? <th className="px-2 py-1">Distribution</th> : null}
          </tr>
        </thead>
        <tbody>
          {parsedRows.map((row) => (
            <tr key={`${row.group}-${row.rank}-${row.label}`} className={tableRowClass}>
              {showGroup ? <td className="rounded-l-xl px-2 py-2 font-medium">{row.group}</td> : null}
              <td className={`px-2 py-2 ${showGroup ? "" : "rounded-l-xl"}`}>{row.rank}</td>
              <td className="px-2 py-2 font-medium">{row.label}</td>
              <td className="px-2 py-2">{formatValue(row.value, valueFormat, { hints: valueHints, samples: valueSamples })}</td>
              {hasShare ? <td className="px-2 py-2">{row.share === null ? "-" : `${row.share.toFixed(2)}%`}</td> : null}
              {hasShare ? (
                <td className="rounded-r-xl px-2 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 w-32 rounded-full bg-slate-200/85">
                      <div
                        className="h-2.5 rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-200"
                        style={{
                          width: `${
                            row.share !== null && maxShare > 0
                              ? Math.min(100, Math.max(0, (row.share / maxShare) * 100))
                              : 0
                          }%`,
                        }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-slate-700">{row.share === null ? "-" : `${row.share.toFixed(1)}%`}</span>
                  </div>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanComparisonModule({ plan, table }: { plan: PresentationPlan; table: DataTable }) {
  const entityHeader = bindingHeaderLabel(plan, "entity_label", "entity");
  const leftHeader = bindingHeaderLabel(plan, "left_value", semanticRoleLabel("left_value"));
  const rightHeader = bindingHeaderLabel(plan, "right_value", semanticRoleLabel("right_value"));
  const deltaHeader = bindingHeaderLabel(plan, "delta_value", semanticRoleLabel("delta_value"));
  const deltaPctHeader = bindingHeaderLabel(plan, "delta_pct", semanticRoleLabel("delta_pct"));
  const leftFormat = bindingFormatKey(plan, "left_value", "left_value");
  const rightFormat = bindingFormatKey(plan, "right_value", "right_value");
  const deltaFormat = bindingFormatKey(plan, "delta_value", rightFormat);
  const parsedRows = useMemo(() => {
    const sorted = sortRowsByPlan(table.rows, plan);
    return sorted.map((row, index) => {
      const left = asNumber(resolvePlanBinding(row, plan, "left_value", index));
      const right = asNumber(resolvePlanBinding(row, plan, "right_value", index));
      const computedDelta = left !== null && right !== null ? right - left : null;
      const delta = computedDelta ?? asNumber(resolvePlanBinding(row, plan, "delta_value", index));
      const deltaPct =
        asNumber(resolvePlanBinding(row, plan, "delta_pct", index)) ??
        (left !== null && left !== 0 && delta !== null ? (delta / left) * 100 : null);
      return {
        label: String(resolvePlanBinding(row, plan, "entity_label", index) ?? `Entity ${index + 1}`),
        left,
        right,
        delta,
        deltaPct,
      };
    });
  }, [plan, table.rows]);
  const leftSamples = parsedRows.map((row) => row.left);
  const rightSamples = parsedRows.map((row) => row.right);
  const deltaSamples = parsedRows.map((row) => row.delta);
  const leftHints = [plan.title, plan.scopeLabel, leftHeader];
  const rightHints = [plan.title, plan.scopeLabel, rightHeader];
  const deltaHints = [plan.title, plan.scopeLabel, deltaHeader];
  const hasDistinctSides = parsedRows.some(
    (row) => row.left !== null && row.right !== null && Math.abs(row.right - row.left) > 0.00001,
  );
  const hasDelta = parsedRows.some((row) => row.delta !== null && Math.abs(row.delta) > 0.00001);
  const hasDeltaPct = parsedRows.some((row) => row.deltaPct !== null && Math.abs(row.deltaPct) > 0.00001);
  const uniqueHeaders = resolveUniqueLabels([
    { id: "left", label: leftHeader, semantic: semanticRoleLabel("left_value") },
    { id: "right", label: rightHeader, semantic: semanticRoleLabel("right_value") },
    { id: "delta", label: deltaHeader, semantic: semanticRoleLabel("delta_value") },
    { id: "deltaPct", label: deltaPctHeader, semantic: semanticRoleLabel("delta_pct") },
  ]);

  return (
    <div className={tableContainerClass}>
      <table className={tableClass}>
        <thead>
          <tr className={tableHeadClass}>
            <th className="px-2 py-1">{entityHeader}</th>
            {hasDistinctSides ? <th className="px-2 py-1">{uniqueHeaders.left}</th> : null}
            <th className="px-2 py-1">{hasDistinctSides ? uniqueHeaders.right : rightHeader}</th>
            {hasDelta ? <th className="px-2 py-1">{uniqueHeaders.delta}</th> : null}
            {hasDeltaPct ? <th className="px-2 py-1">{uniqueHeaders.deltaPct}</th> : null}
          </tr>
        </thead>
        <tbody>
          {parsedRows.map((row) => (
            <tr key={row.label} className={tableRowClass}>
              <td className="rounded-l-xl px-2 py-2 font-medium">{row.label}</td>
              {hasDistinctSides ? (
                <td className="px-2 py-2">{formatValue(row.left, leftFormat, { hints: leftHints, samples: leftSamples })}</td>
              ) : null}
              <td className={`px-2 py-2 ${!hasDelta && !hasDeltaPct ? "rounded-r-xl" : ""}`}>
                {formatValue(hasDistinctSides ? row.right : row.left ?? row.right, rightFormat, {
                  hints: rightHints,
                  samples: rightSamples,
                })}
              </td>
              {hasDelta ? (
                <td className={`px-2 py-2 font-semibold ${deltaColorClass(row.delta)} ${!hasDeltaPct ? "rounded-r-xl" : ""}`}>
                  {formatValue(row.delta, deltaFormat, { hints: deltaHints, samples: deltaSamples })}
                </td>
              ) : null}
              {hasDeltaPct ? (
                <td className="rounded-r-xl px-2 py-2">{row.deltaPct === null ? "-" : `${row.deltaPct.toFixed(2)}%`}</td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanTrendModule({ plan, table }: { plan: PresentationPlan; table: DataTable }) {
  const valueFormat = bindingFormatKey(plan, "value", "value");
  const deltaFormat = bindingFormatKey(plan, "delta_vs_prev", valueFormat);
  const periodHeader = bindingHeaderLabel(plan, "period_label", "period");
  const seriesHeader = prettifyColumn(bindingFormatKey(plan, "series_label", "series"));
  const valueHeader = bindingHeaderLabel(plan, "value", semanticRoleLabel("value"));
  const deltaHeader = plan.bindings["delta_vs_prev"]
    ? prettifyColumn(bindingFormatKey(plan, "delta_vs_prev", "delta_vs_prev"))
    : "Change vs Previous";
  const deltaPctHeader = plan.bindings["delta_pct"]
    ? prettifyColumn(bindingFormatKey(plan, "delta_pct", "change_pct"))
    : "Change %";
  const trendRows = useMemo(() => {
    const sorted = sortRowsByPlan(table.rows, plan);
    const prevBySeries = new Map<string, number>();
    return sorted.map((row, index) => {
      const value = asNumber(resolvePlanBinding(row, plan, "value", index)) ?? 0;
      const series = String(resolvePlanBinding(row, plan, "series_label", index) ?? "Primary");
      const prev = prevBySeries.get(series) ?? null;
      const explicitDelta = asNumber(resolvePlanBinding(row, plan, "delta_vs_prev", index));
      const explicitDeltaPct = asNumber(resolvePlanBinding(row, plan, "delta_pct", index));
      const delta = explicitDelta ?? (prev === null ? null : value - prev);
      const deltaPct = explicitDeltaPct ?? (prev === null || prev === 0 || delta === null ? null : (delta / prev) * 100);
      prevBySeries.set(series, value);
      return {
        periodLabel: resolvePlanBinding(row, plan, "period_label", index),
        periodOrder: resolvePlanBinding(row, plan, "period_order", index),
        seriesLabel: series,
        value,
        delta,
        deltaPct,
        index,
      };
    });
  }, [plan, table.rows]);

  const seriesCount = new Set(trendRows.map((row) => row.seriesLabel)).size;
  const showSeries = seriesCount > 1 || Boolean(plan.bindings["series_label"]);
  const firstSeries = trendRows[0]?.seriesLabel;
  const sparklineRows = trendRows.filter((row) => row.seriesLabel === firstSeries);
  const sparklineValues = sparklineRows.map((row) => row.value);
  const valueHints = [plan.title, plan.scopeLabel, valueHeader];
  const valueSamples = trendRows.map((row) => row.value);
  const deltaSamples = trendRows.map((row) => row.delta);
  const labelSet = resolveUniqueLabels([
    { id: "value", label: valueHeader, semantic: semanticRoleLabel("value") },
    { id: "delta", label: deltaHeader, semantic: semanticRoleLabel("delta_value") },
    { id: "deltaPct", label: deltaPctHeader, semantic: semanticRoleLabel("delta_pct") },
  ]);

  return (
    <>
      <Sparkline
        values={sparklineValues}
        xLabels={sparklineRows.map((row) => formatMonthLabel(row.periodLabel))}
        valueFormatKey={valueFormat}
        contextHints={valueHints}
      />
      <div className={tableContainerClass}>
        <table className={tableClass}>
          <thead>
            <tr className={tableHeadClass}>
              <th className="px-2 py-1">{periodHeader}</th>
              {showSeries ? <th className="px-2 py-1">{seriesHeader}</th> : null}
              <th className="px-2 py-1">{labelSet.value}</th>
              <th className="px-2 py-1">{labelSet.delta}</th>
              <th className="px-2 py-1">{labelSet.deltaPct}</th>
            </tr>
          </thead>
          <tbody>
            {trendRows.map((row) => (
              <tr key={`${row.seriesLabel}-${String(row.periodOrder)}-${row.index}`} className={tableRowClass}>
                <td className="rounded-l-xl px-2 py-2 font-medium">{formatMonthLabel(row.periodLabel)}</td>
                {showSeries ? <td className="px-2 py-2">{row.seriesLabel}</td> : null}
                <td className="px-2 py-2">{formatValue(row.value, valueFormat, { hints: valueHints, samples: valueSamples })}</td>
                <td className={`px-2 py-2 font-semibold ${deltaColorClass(row.delta)}`}>
                  {formatValue(row.delta, deltaFormat, { hints: valueHints, samples: deltaSamples })}
                </td>
                <td className={`rounded-r-xl px-2 py-2 font-semibold ${deltaColorClass(row.delta)}`}>
                  {row.deltaPct === null ? "-" : `${row.deltaPct.toFixed(2)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function PlanDistributionModule({ plan, table }: { plan: PresentationPlan; table: DataTable }) {
  const bucketHeader = bindingHeaderLabel(plan, "bucket_label", "bucket");
  const shareHeader = bindingHeaderLabel(plan, "share_of_scope", "share_pct");
  const cumulativeHeader = bindingHeaderLabel(plan, "cumulative_share", "cumulative_pct");
  const valueFormat = bindingFormatKey(plan, "value", "value");
  const valueHeader = bindingHeaderLabel(plan, "value", "value");
  const rows = useMemo(() => {
    const sorted = sortRowsByPlan(table.rows, plan);
    return sorted.map((row, index) => ({
      bucket: String(resolvePlanBinding(row, plan, "bucket_label", index) ?? `Bucket ${index + 1}`),
      value: asNumber(resolvePlanBinding(row, plan, "value", index)),
      share: asNumber(resolvePlanBinding(row, plan, "share_of_scope", index)),
      cumulative: asNumber(resolvePlanBinding(row, plan, "cumulative_share", index)),
    }));
  }, [plan, table.rows]);

  const maxValue = useMemo(
    () =>
      Math.max(
        0,
        ...rows
          .map((row) => row.value)
          .filter((value): value is number => value !== null),
      ),
    [rows],
  );
  const hasShare = rows.some((row) => row.share !== null);
  const hasCumulative = rows.some((row) => row.cumulative !== null);
  const valueHints = [plan.title, plan.scopeLabel, valueHeader];
  const valueSamples = rows.map((row) => row.value);

  return (
    <div className={tableContainerClass}>
      <table className={tableClass}>
        <thead>
          <tr className={tableHeadClass}>
            <th className="px-2 py-1">{bucketHeader}</th>
            <th className="px-2 py-1">{valueHeader}</th>
            {hasShare ? <th className="px-2 py-1">{shareHeader}</th> : null}
            {hasCumulative ? <th className="px-2 py-1">{cumulativeHeader}</th> : null}
            <th className="px-2 py-1">Bar</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.bucket} className={tableRowClass}>
              <td className="rounded-l-xl px-2 py-2 font-medium">{row.bucket}</td>
              <td className="px-2 py-2">{formatValue(row.value, valueFormat, { hints: valueHints, samples: valueSamples })}</td>
              {hasShare ? <td className="px-2 py-2">{row.share === null ? "-" : `${row.share.toFixed(2)}%`}</td> : null}
              {hasCumulative ? <td className="px-2 py-2">{row.cumulative === null ? "-" : `${row.cumulative.toFixed(2)}%`}</td> : null}
              <td className="rounded-r-xl px-2 py-2">
                <div className="h-2.5 w-32 rounded-full bg-slate-200/85">
                  <div
                    className="h-2.5 rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500"
                    style={{
                      width: `${row.value !== null && maxValue > 0 ? Math.min(100, Math.max(0, (row.value / maxValue) * 100)) : 0}%`,
                    }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanSnapshotModule({ plan, table }: { plan: PresentationPlan; table: DataTable }) {
  const valueFormat = bindingFormatKey(plan, "kpi_value", "kpi_value");
  const cards = useMemo(() => {
    const sorted = sortRowsByPlan(table.rows, plan);
    return sorted.slice(0, 8).map((row, index) => ({
      label: String(resolvePlanBinding(row, plan, "kpi_label", index) ?? `KPI ${index + 1}`),
      value: asNumber(resolvePlanBinding(row, plan, "kpi_value", index)),
      unit: String(resolvePlanBinding(row, plan, "kpi_unit", index) ?? ""),
      context: String(resolvePlanBinding(row, plan, "context_label", index) ?? ""),
    }));
  }, [plan, table.rows]);

  if (cards.length === 0) {
    return <p className="mt-3 text-sm text-slate-600">No snapshot rows were returned for this request.</p>;
  }
  const valueHints = [plan.title, plan.scopeLabel];
  const valueSamples = cards.map((card) => card.value);

  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map((card) => (
        <article
          key={card.label}
          className="rounded-xl border border-slate-200/90 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(246,250,255,0.95))] p-3 shadow-[inset_0_0_0_1px_rgba(226,232,240,0.45)]"
        >
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{card.label}</p>
          <p className="mt-1.5 text-sm font-semibold text-slate-900">
            {card.unit
              ? `${formatValue(card.value, valueFormat, { hints: valueHints, samples: valueSamples })} ${card.unit}`
              : formatValue(card.value, valueFormat, { hints: valueHints, samples: valueSamples })}
          </p>
          {card.context ? <p className="mt-1 text-xs text-slate-600">{card.context}</p> : null}
        </article>
      ))}
    </div>
  );
}

function preferredArtifact(
  artifacts: AnalysisArtifact[],
  primaryVisual: PrimaryVisual | undefined,
): AnalysisArtifact | undefined {
  const preferredKind = primaryVisual?.artifactKind;
  if (!preferredKind) return artifacts[0];
  return artifacts.find((artifact) => artifact.kind === preferredKind) ?? artifacts[0];
}

export function EvidenceTable({
  rows,
  artifacts,
  primaryVisual,
  presentationPlan,
  analysisType,
  dataTables,
}: {
  rows: EvidenceRow[];
  artifacts?: AnalysisArtifact[];
  primaryVisual?: PrimaryVisual;
  presentationPlan?: PresentationPlan;
  analysisType?: AnalysisType;
  dataTables?: DataTable[];
}) {
  const [legacySortBy, setLegacySortBy] = useState<LegacySortKey>("contribution");
  const [activeArtifactId, setActiveArtifactId] = useState<string>("");

  const moduleArtifacts = useMemo(() => (artifacts ?? []).filter((artifact) => artifact.rows.length > 0), [artifacts]);
  const resolvedVisualType = useMemo(
    () =>
      resolveVisualType({
        analysisType,
        primaryVisual,
        artifacts: moduleArtifacts,
        dataTables,
      }),
    [analysisType, primaryVisual, moduleArtifacts, dataTables],
  );
  const compatibleArtifacts = useMemo(() => {
    const allowedKinds = artifactKindsForVisualType(resolvedVisualType);
    if (!allowedKinds.length) return moduleArtifacts;
    const allowed = new Set(allowedKinds);
    return moduleArtifacts.filter((artifact) => allowed.has(artifact.kind) && isArtifactFinished(artifact));
  }, [moduleArtifacts, resolvedVisualType]);

  useEffect(() => {
    if (compatibleArtifacts.length === 0) {
      setActiveArtifactId("");
      return;
    }
    const hasActive = compatibleArtifacts.some((artifact) => artifact.id === activeArtifactId);
    if (!hasActive) {
      const preferred = preferredArtifact(compatibleArtifacts, primaryVisual);
      setActiveArtifactId(preferred?.id ?? compatibleArtifacts[0].id);
    }
  }, [compatibleArtifacts, activeArtifactId, primaryVisual]);

  const activeArtifact = useMemo(
    () => compatibleArtifacts.find((artifact) => artifact.id === activeArtifactId) ?? compatibleArtifacts[0],
    [compatibleArtifacts, activeArtifactId],
  );
  const fallbackSnapshotArtifact = useMemo(
    () => moduleArtifacts.find((artifact) => isArtifactFinished(artifact)),
    [moduleArtifacts],
  );
  const firstDataTable = dataTables?.[0];
  const planTable = useMemo(
    () => dataTables?.find((table) => table.id === presentationPlan?.tableId),
    [dataTables, presentationPlan?.tableId],
  );

  const sortedLegacyRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      if (legacySortBy === "segment") return a.segment.localeCompare(b.segment);
      return Number(b[legacySortBy]) - Number(a[legacySortBy]);
    });
  }, [rows, legacySortBy]);

  if (presentationPlan && planTable) {
    return (
      <section className={moduleSectionClass}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-slate-900">{presentationPlan.title}</h3>
            <p className="text-xs text-slate-600">{presentationPlan.scopeLabel}</p>
          </div>
          <span className="rounded-full border border-slate-200/80 bg-white/85 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-700">
            {prettifyColumn(presentationPlan.visualType)}
          </span>
        </div>

        {presentationPlan.visualType === "ranking" ? <PlanRankingModule plan={presentationPlan} table={planTable} /> : null}
        {presentationPlan.visualType === "comparison" ? (
          <PlanComparisonModule plan={presentationPlan} table={planTable} />
        ) : null}
        {presentationPlan.visualType === "trend" ? <PlanTrendModule plan={presentationPlan} table={planTable} /> : null}
        {presentationPlan.visualType === "distribution" ? (
          <PlanDistributionModule plan={presentationPlan} table={planTable} />
        ) : null}
        {presentationPlan.visualType === "snapshot" ? <PlanSnapshotModule plan={presentationPlan} table={planTable} /> : null}
        {presentationPlan.visualType === "table" ? <TableModule table={planTable} /> : null}
      </section>
    );
  }

  if (resolvedVisualType === "snapshot" || resolvedVisualType === "table") {
    return (
      <section className={moduleSectionClass}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-slate-900">
              {primaryVisual?.title?.trim() || (resolvedVisualType === "snapshot" ? "Snapshot" : "Data Table")}
            </h3>
            {primaryVisual?.description?.trim() ? <p className="text-xs text-slate-600">{primaryVisual.description.trim()}</p> : null}
          </div>
          <span className="rounded-full border border-slate-200/80 bg-white/85 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-700">
            {resolvedVisualType === "snapshot" ? "Snapshot" : "Table"}
          </span>
        </div>

        {resolvedVisualType === "snapshot" ? (
          firstDataTable ? (
            <SnapshotModule table={firstDataTable} />
          ) : fallbackSnapshotArtifact ? (
            <SnapshotArtifactModule artifact={fallbackSnapshotArtifact} />
          ) : (
            <p className="mt-3 text-sm text-slate-600">No snapshot rows were returned for this request.</p>
          )
        ) : firstDataTable ? (
          <TableModule table={firstDataTable} />
        ) : fallbackSnapshotArtifact ? (
          <GenericModule artifact={fallbackSnapshotArtifact} />
        ) : (
          <p className="mt-3 text-sm text-slate-600">No table rows were returned for this request.</p>
        )}
      </section>
    );
  }

  if (activeArtifact) {
    const visualTitle = primaryVisual?.title?.trim() || activeArtifact.title;
    const visualDescription = primaryVisual?.description?.trim() || artifactDescription(activeArtifact);
    return (
      <section className={moduleSectionClass}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-slate-900">{visualTitle}</h3>
            <p className="text-xs text-slate-600">{visualDescription}</p>
          </div>
          <span className="rounded-full border border-slate-200/80 bg-white/85 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-700">
            {artifactLabel(activeArtifact.kind)}
          </span>
        </div>

        {compatibleArtifacts.length > 1 ? (
          <div className="mt-3 inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-full bg-slate-100 p-1">
            {compatibleArtifacts.map((artifact) => (
              <button
                key={artifact.id}
                type="button"
                onClick={() => setActiveArtifactId(artifact.id)}
                className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold transition ${
                  artifact.id === activeArtifact.id ? "bg-white text-slate-900 shadow" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {artifactLabel(artifact.kind)}
              </button>
            ))}
          </div>
        ) : null}

        {activeArtifact.kind === "ranking_breakdown" ? <RankingModule artifact={activeArtifact} /> : null}
        {activeArtifact.kind === "comparison_breakdown" || activeArtifact.kind === "delta_breakdown" ? (
          <ComparisonModule artifact={activeArtifact} />
        ) : null}
        {activeArtifact.kind === "trend_breakdown" ? <TrendModule artifact={activeArtifact} /> : null}
        {activeArtifact.kind === "distribution_breakdown" ? <DistributionModule artifact={activeArtifact} /> : null}
        {!["ranking_breakdown", "comparison_breakdown", "delta_breakdown", "trend_breakdown", "distribution_breakdown"].includes(
          activeArtifact.kind,
        ) ? (
          <GenericModule artifact={activeArtifact} />
        ) : null}
      </section>
    );
  }

  if (!rows.length) {
    return null;
  }

  return (
    <section className={moduleSectionClass}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold tracking-wide text-slate-900">Evidence Breakdown</h3>
          <p className="text-xs text-slate-600">Interactive evidence ranked by impact.</p>
        </div>
        <div className="inline-flex items-center rounded-full bg-slate-100 p-1">
          {legacySortOptions.map((option) => (
            <button
              key={option.key}
              onClick={() => setLegacySortBy(option.key)}
              className={`rounded-full px-2.5 py-1 text-xs font-semibold transition ${
                legacySortBy === option.key ? "bg-white text-slate-900 shadow" : "text-slate-600 hover:text-slate-900"
              }`}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className={tableContainerClass}>
        <table className="w-full min-w-[580px] border-separate border-spacing-y-1.5 text-left text-sm">
          <thead>
            <tr className={tableHeadClass}>
              <th className="px-2 py-1">Segment</th>
              <th className="px-2 py-1">Prior</th>
              <th className="px-2 py-1">Current</th>
              <th className="px-2 py-1">Delta</th>
              <th className="px-2 py-1">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {sortedLegacyRows.map((row) => (
              <tr key={row.segment} className={tableRowClass}>
                <td className="rounded-l-xl px-2 py-2 font-medium">{row.segment}</td>
                <td className="px-2 py-2">{row.prior.toFixed(2)}</td>
                <td className="px-2 py-2">{row.current.toFixed(2)}</td>
                <td className="px-2 py-2">{row.changeBps.toFixed(2)}</td>
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
