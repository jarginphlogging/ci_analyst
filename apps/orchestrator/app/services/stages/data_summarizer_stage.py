from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.models import SqlExecutionResult


def _safe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if pd.isna(value):
        return None
    return str(value)


def _series_snapshot(series: pd.Series) -> dict[str, float]:
    cleaned = pd.to_numeric(series, errors="coerce").dropna()
    if cleaned.empty:
        return {}
    return {
        "min": round(float(cleaned.min()), 6),
        "p10": round(float(cleaned.quantile(0.10)), 6),
        "median": round(float(cleaned.median()), 6),
        "mean": round(float(cleaned.mean()), 6),
        "p90": round(float(cleaned.quantile(0.90)), 6),
        "max": round(float(cleaned.max()), 6),
        "sum": round(float(cleaned.sum()), 6),
    }


def _is_date_like(series: pd.Series) -> bool:
    if series.empty:
        return False
    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    non_null_values = series.dropna()
    if non_null_values.empty:
        return False

    sample = non_null_values.astype(str).head(40)
    iso_like_ratio = (
        sample.str.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T].*)?$", na=False).sum() / max(1, len(sample))
    )
    if iso_like_ratio < 0.6:
        return False

    parsed = pd.to_datetime(sample, errors="coerce", utc=False, format="mixed")
    non_null = int(parsed.notna().sum())
    denominator = max(1, int(sample.notna().sum()))
    return (non_null / denominator) >= 0.8


def _sample_rows(df: pd.DataFrame, max_rows: int = 3, max_columns: int = 8) -> list[dict[str, Any]]:
    if df.empty:
        return []
    selected_columns = list(df.columns[:max_columns])
    sample_df = df[selected_columns].head(max_rows)
    return [{column: _safe_json(value) for column, value in row.items()} for row in sample_df.to_dict(orient="records")]


def _top_values(series: pd.Series, top_n: int = 5) -> list[dict[str, Any]]:
    value_counts = series.fillna("<NULL>").astype(str).value_counts(dropna=False).head(top_n)
    total = max(1, int(series.shape[0]))
    rows: list[dict[str, Any]] = []
    for value, count in value_counts.items():
        rows.append(
            {
                "value": value,
                "count": int(count),
                "sharePct": round((int(count) / total) * 100.0, 3),
            }
        )
    return rows


@dataclass(frozen=True)
class DataSummarizerStage:
    max_numeric_columns: int = 10
    max_categorical_columns: int = 6

    def summarize_tables(self, *, results: list[SqlExecutionResult], message: str) -> list[dict[str, Any]]:
        table_summaries: list[dict[str, Any]] = []
        for index, result in enumerate(results, start=1):
            df = pd.DataFrame(result.rows)
            if df.empty:
                table_summaries.append(
                    {
                        "step": index,
                        "rowCount": result.rowCount,
                        "columnCount": 0,
                        "columns": [],
                        "nullRatePct": 100.0,
                        "sampleRows": [],
                        "numericStats": {},
                        "categoricalStats": {},
                        "dateStats": {},
                        "comparisonSignals": {},
                    }
                )
                continue

            null_cells = int(df.isna().sum().sum())
            total_cells = max(1, int(df.shape[0] * df.shape[1]))
            null_rate_pct = round((null_cells / total_cells) * 100.0, 3)

            numeric_columns: list[str] = []
            date_columns: list[str] = []
            categorical_columns: list[str] = []
            for column in df.columns:
                series = df[column]
                if pd.api.types.is_numeric_dtype(series):
                    numeric_columns.append(column)
                    continue
                if _is_date_like(series):
                    date_columns.append(column)
                    continue
                categorical_columns.append(column)

            numeric_stats: dict[str, dict[str, float]] = {}
            for column in numeric_columns[: self.max_numeric_columns]:
                snapshot = _series_snapshot(df[column])
                if snapshot:
                    numeric_stats[column] = snapshot

            date_stats: dict[str, dict[str, Any]] = {}
            for column in date_columns[:3]:
                parsed = pd.to_datetime(df[column], errors="coerce", utc=False)
                cleaned = parsed.dropna()
                if cleaned.empty:
                    continue
                date_stats[column] = {
                    "min": str(cleaned.min()),
                    "max": str(cleaned.max()),
                    "uniquePeriods": int(cleaned.nunique()),
                }

            categorical_stats: dict[str, dict[str, Any]] = {}
            for column in categorical_columns[: self.max_categorical_columns]:
                series = df[column]
                categorical_stats[column] = {
                    "uniqueValues": int(series.astype(str).nunique(dropna=True)),
                    "topValues": _top_values(series),
                }

            comparison_signals: dict[str, Any] = {}
            lowered_columns = {str(column).lower(): str(column) for column in df.columns}
            current_col = next((original for key, original in lowered_columns.items() if "current" in key), None)
            prior_col = next(
                (original for key, original in lowered_columns.items() if any(token in key for token in ["prior", "previous", "prev"])),
                None,
            )
            change_col = next((original for key, original in lowered_columns.items() if any(token in key for token in ["change", "delta", "yoy", "mom"])), None)
            if change_col:
                change_series = pd.to_numeric(df[change_col], errors="coerce")
                if change_series.notna().any():
                    idx = int(change_series.abs().idxmax())
                    comparison_signals = {
                        "largestAbsoluteChange": round(float(change_series.iloc[idx]), 6),
                        "largestChangeRow": {key: _safe_json(value) for key, value in df.iloc[idx].to_dict().items()},
                    }
            elif current_col and prior_col:
                current_series = pd.to_numeric(df[current_col], errors="coerce")
                prior_series = pd.to_numeric(df[prior_col], errors="coerce")
                change_series = current_series - prior_series
                if change_series.notna().any():
                    idx = int(change_series.abs().idxmax())
                    comparison_signals = {
                        "derivedLargestAbsoluteChange": round(float(change_series.iloc[idx]), 6),
                        "largestChangeRow": {key: _safe_json(value) for key, value in df.iloc[idx].to_dict().items()},
                    }

            table_summaries.append(
                {
                    "step": index,
                    "rowCount": int(result.rowCount),
                    "columnCount": int(df.shape[1]),
                    "columns": [str(column) for column in df.columns],
                    "nullRatePct": null_rate_pct,
                    "sampleRows": _sample_rows(df),
                    "numericStats": numeric_stats,
                    "categoricalStats": categorical_stats,
                    "dateStats": date_stats,
                    "comparisonSignals": comparison_signals,
                }
            )
        return table_summaries

    def summarize_for_prompt(self, *, results: list[SqlExecutionResult], message: str) -> str:
        if not results:
            return "No SQL results were returned."

        table_summaries = self.summarize_tables(results=results, message=message)
        portfolio_rows = sum(item.get("rowCount", 0) for item in table_summaries)
        summary_package = {
            "portfolioSummary": {
                "tableCount": len(table_summaries),
                "totalRows": portfolio_rows,
                "messageIntent": message,
            },
            "tableSummaries": table_summaries,
        }
        return json.dumps(summary_package, ensure_ascii=True, separators=(",", ":"))
