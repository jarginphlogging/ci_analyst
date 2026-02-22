"use client";

import { useEffect, useMemo, useState } from "react";
import type { AnalysisArtifact, DataCell, EvidenceRow } from "@/lib/types";

type LegacySortKey = "segment" | "prior" | "current" | "changeBps" | "contribution";
type RankingSortKey = "rank" | "label" | "value" | "share";
type ComparisonSortKey = "label" | "prior" | "current" | "change";
type SortDirection = "asc" | "desc";

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

function formatValue(value: number | null, key: string): string {
  if (value === null) return "-";
  const lower = key.toLowerCase();
  if (lower.includes("pct") || lower.includes("share")) return `${value.toFixed(2)}%`;
  if (lower.includes("spend") || lower.includes("sales") || lower.includes("revenue") || lower.includes("amount")) {
    return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  }
  if (lower.includes("transactions") || lower.includes("count")) {
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

function parseTime(value: DataCell | undefined): number {
  if (!value) return Number.POSITIVE_INFINITY;
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
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

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[620px] border-separate border-spacing-y-2 text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500">
              <th className="px-2 py-1">Rank</th>
              <th className="px-2 py-1">{prettifyColumn(dimensionKey)}</th>
              <th className="px-2 py-1">{prettifyColumn(valueKey)}</th>
              <th className="px-2 py-1">Share</th>
              <th className="px-2 py-1">Share Bar</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <tr key={`${row.rank}-${row.label}`} className="rounded-xl bg-slate-50 text-slate-800">
                <td className="rounded-l-xl px-2 py-2 font-medium">{row.rank}</td>
                <td className="px-2 py-2 font-medium">{row.label}</td>
                <td className="px-2 py-2">{formatValue(row.value, valueKey)}</td>
                <td className="px-2 py-2">{row.share.toFixed(2)}%</td>
                <td className="rounded-r-xl px-2 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2.5 w-32 rounded-full bg-slate-200">
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

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[620px] border-separate border-spacing-y-2 text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500">
              <th className="px-2 py-1">{prettifyColumn(dimensionKey)}</th>
              <th className="px-2 py-1">Prior</th>
              <th className="px-2 py-1">Current</th>
              <th className="px-2 py-1">Change</th>
              <th className="px-2 py-1">Change %</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <tr key={row.label} className="rounded-xl bg-slate-50 text-slate-800">
                <td className="rounded-l-xl px-2 py-2 font-medium">{row.label}</td>
                <td className="px-2 py-2">{formatValue(row.prior, "prior")}</td>
                <td className="px-2 py-2">{formatValue(row.current, "current")}</td>
                <td className={`px-2 py-2 font-semibold ${(row.change ?? 0) >= 0 ? "text-rose-700" : "text-emerald-700"}`}>
                  {formatValue(row.change, "change")}
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

  const sortedRows = useMemo(
    () => [...artifact.rows].sort((a, b) => parseTime(a[timeKey]) - parseTime(b[timeKey])),
    [artifact.rows, timeKey],
  );

  const values = sortedRows.map((row) => asNumber(row[valueKey]) ?? 0);
  const maxAbs = Math.max(1, ...values.map((value) => Math.abs(value)));

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[620px] border-separate border-spacing-y-2 text-left text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-slate-500">
            <th className="px-2 py-1">{prettifyColumn(timeKey)}</th>
            <th className="px-2 py-1">{prettifyColumn(valueKey)}</th>
            <th className="px-2 py-1">Period Change</th>
            <th className="px-2 py-1">Signal</th>
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, index) => {
            const value = asNumber(row[valueKey]) ?? 0;
            const delta = asNumber(row.period_change);
            const width = Math.max(4, (Math.abs(value) / maxAbs) * 100);
            return (
              <tr key={`${String(row[timeKey])}-${index}`} className="rounded-xl bg-slate-50 text-slate-800">
                <td className="rounded-l-xl px-2 py-2 font-medium">{String(row[timeKey] ?? "-")}</td>
                <td className="px-2 py-2">{formatValue(value, valueKey)}</td>
                <td className={`px-2 py-2 font-semibold ${delta === null || delta >= 0 ? "text-rose-700" : "text-emerald-700"}`}>
                  {delta === null ? "-" : formatValue(delta, "delta")}
                </td>
                <td className="rounded-r-xl px-2 py-2">
                  <div className="h-2.5 w-40 rounded-full bg-slate-200">
                    <div
                      className="h-2.5 rounded-full bg-gradient-to-r from-sky-500 to-cyan-500"
                      style={{ width: `${width}%` }}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DistributionModule({ artifact }: { artifact: AnalysisArtifact }) {
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {artifact.rows.map((row, index) => (
        <article key={`${String(row.stat)}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{String(row.stat ?? "stat")}</p>
          <p className="mt-1.5 text-sm font-semibold text-slate-900">{formatValue(asNumber(row.value), artifact.valueKey ?? "value")}</p>
          {row.label ? <p className="mt-1 text-xs text-slate-600">{String(row.label)}</p> : null}
        </article>
      ))}
    </div>
  );
}

function GenericModule({ artifact }: { artifact: AnalysisArtifact }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[620px] border-separate border-spacing-y-2 text-left text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-slate-500">
            {artifact.columns.map((column) => (
              <th key={column} className="px-2 py-1">
                {prettifyColumn(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {artifact.rows.map((row, index) => (
            <tr key={`${artifact.id}-${index}`} className="rounded-xl bg-slate-50 text-slate-800">
              {artifact.columns.map((column, colIndex) => (
                <td
                  key={`${artifact.id}-${index}-${column}`}
                  className={`px-2 py-2 ${colIndex === 0 ? "rounded-l-xl font-medium" : ""} ${
                    colIndex === artifact.columns.length - 1 ? "rounded-r-xl" : ""
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
  );
}

export function EvidenceTable({ rows, artifacts }: { rows: EvidenceRow[]; artifacts?: AnalysisArtifact[] }) {
  const [legacySortBy, setLegacySortBy] = useState<LegacySortKey>("contribution");
  const [activeArtifactId, setActiveArtifactId] = useState<string>("");

  const moduleArtifacts = useMemo(() => (artifacts ?? []).filter((artifact) => artifact.rows.length > 0), [artifacts]);

  useEffect(() => {
    if (moduleArtifacts.length === 0) {
      setActiveArtifactId("");
      return;
    }
    const hasActive = moduleArtifacts.some((artifact) => artifact.id === activeArtifactId);
    if (!hasActive) {
      setActiveArtifactId(moduleArtifacts[0].id);
    }
  }, [moduleArtifacts, activeArtifactId]);

  const activeArtifact = useMemo(
    () => moduleArtifacts.find((artifact) => artifact.id === activeArtifactId) ?? moduleArtifacts[0],
    [moduleArtifacts, activeArtifactId],
  );

  const sortedLegacyRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      if (legacySortBy === "segment") return a.segment.localeCompare(b.segment);
      return Number(b[legacySortBy]) - Number(a[legacySortBy]);
    });
  }, [rows, legacySortBy]);

  if (activeArtifact) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-slate-900">{activeArtifact.title}</h3>
            <p className="text-xs text-slate-600">{artifactDescription(activeArtifact)}</p>
          </div>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
            {artifactLabel(activeArtifact.kind)}
          </span>
        </div>

        {moduleArtifacts.length > 1 ? (
          <div className="mt-3 inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-full bg-slate-100 p-1">
            {moduleArtifacts.map((artifact) => (
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
    <section className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-[0_8px_24px_rgba(14,44,68,0.08)]">
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

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[580px] border-separate border-spacing-y-2 text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500">
              <th className="px-2 py-1">Segment</th>
              <th className="px-2 py-1">Prior</th>
              <th className="px-2 py-1">Current</th>
              <th className="px-2 py-1">Delta</th>
              <th className="px-2 py-1">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {sortedLegacyRows.map((row) => (
              <tr key={row.segment} className="rounded-xl bg-slate-50 text-slate-800">
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
