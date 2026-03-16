from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, cast

from app.models import ComparisonSignal, EvidenceProvenance, FactSignal, SalienceDriver, SqlExecutionResult, SupportStatus
from app.services.table_analysis_common import (
    JsonValue,
    _comparison_columns,
    _metric_unit,
    _period_token_label,
    _period_token_sort_key,
    _periodized_metric_signature,
    _profile_rows,
    _to_float,
)


def _period_label_from_row(row: dict[str, JsonValue], time_columns: list[str]) -> str:
    if not row:
        return "unknown_period"

    from_key = next((key for key in row.keys() if "from" in key.lower() or "start" in key.lower() or "min" in key.lower()), None)
    through_key = next((key for key in row.keys() if "through" in key.lower() or "end" in key.lower() or "max" in key.lower()), None)
    if from_key and through_key:
        from_value = row.get(from_key)
        through_value = row.get(through_key)
        if from_value is not None and through_value is not None:
            return f"{from_value} to {through_value}"

    if time_columns:
        first = row.get(time_columns[0])
        if first is not None:
            return str(first)
    return "unknown_period"


def _period_sort_key(period: str, fallback_index: int) -> tuple[int, float]:
    raw = period.strip()
    if not raw:
        return (1, float(fallback_index))

    date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", raw)
    if date_match:
        try:
            return (0, datetime.fromisoformat(date_match.group(1)).timestamp())
        except ValueError:
            pass

    year_match = re.search(r"(20\d{2})", raw)
    if year_match:
        try:
            return (0, float(int(year_match.group(1))))
        except ValueError:
            pass

    return (1, float(fallback_index))


def _intent_alignment_score(metric_label: str, message: str) -> float:
    text = message.lower()
    metric = metric_label.lower()
    if not text.strip():
        return 0.6
    metric_tokens = [token for token in re.split(r"[^a-z0-9]+", metric) if len(token) >= 3]
    if any(token in text for token in metric_tokens):
        return 1.0
    if any(token in metric for token in ("sales", "spend", "revenue", "transactions", "amount", "avg", "average")) and any(
        token in text for token in ("sales", "spend", "revenue", "transactions", "amount", "avg", "average")
    ):
        return 0.8
    return 0.5


def _support_status(*, reliability: float, completeness: float) -> SupportStatus:
    combined = (0.7 * reliability) + (0.3 * completeness)
    if combined >= 0.85:
        return "strong"
    if combined >= 0.65:
        return "moderate"
    return "weak"


def _salience_score(
    *,
    intent: float,
    magnitude: float,
    completeness: float,
    reliability: float,
    period_compatibility: float,
) -> tuple[float, SalienceDriver]:
    components: dict[SalienceDriver, float] = {
        "intent": 0.36 * intent,
        "magnitude": 0.24 * magnitude,
        "completeness": 0.14 * completeness,
        "reliability": 0.16 * reliability,
        "period_compatibility": 0.10 * period_compatibility,
    }
    driver = max(components.items(), key=lambda item: item[1])[0]
    return sum(components.values()), driver


def build_fact_comparison_signals(
    results: list[SqlExecutionResult],
    *,
    message: str = "",
    max_facts: int = 24,
    max_comparisons: int = 16,
) -> tuple[list[FactSignal], list[ComparisonSignal]]:
    raw_facts: list[dict[str, Any]] = []
    raw_comparisons: list[dict[str, Any]] = []
    single_row_steps: list[dict[str, Any]] = []

    def _paired_prior_value(row: dict[str, Any], metric_key: str) -> tuple[float | None, str | None]:
        normalized = metric_key.strip().lower()
        candidate_keys = [
            f"comparison_{normalized}",
            f"prior_{normalized}",
            f"previous_{normalized}",
        ]
        for candidate in candidate_keys:
            for key in row.keys():
                if key.strip().lower() == candidate:
                    return _to_float(row.get(key)), key
        return None, None

    for step_index, result in enumerate(results, start=1):
        if not result.rows:
            continue
        rows = result.rows
        profile = _profile_rows(rows)
        if not profile.metric_columns:
            continue

        if result.rowCount == 1:
            row = rows[0]
            period = _period_label_from_row(row, profile.time_columns)
            lowered_row = {str(key).strip().lower(): key for key in row.keys()}
            current_period = str(row.get(lowered_row.get("period", ""), "")).strip() or period
            prior_period = (
                str(row.get(lowered_row.get("comparison_period", ""), "")).strip()
                or str(row.get(lowered_row.get("prior_period", ""), "")).strip()
                or str(row.get(lowered_row.get("previous_period", ""), "")).strip()
                or "prior period"
            )
            metrics_for_step: dict[str, float] = {}
            periodized_metrics: dict[str, list[tuple[str, float, str]]] = {}
            for column in profile.metric_columns[:8]:
                lowered_column = column.strip().lower()
                if lowered_column.startswith(("comparison_", "prior_", "previous_")):
                    continue
                value = _to_float(row.get(column))
                if value is None:
                    continue
                metrics_for_step[column] = float(value)
                signature = _periodized_metric_signature(column)
                if signature is not None:
                    metric_root, period_token = signature
                    periodized_metrics.setdefault(metric_root, []).append((period_token, float(value), column))
                raw_facts.append(
                    {
                        "id": f"fact_s{step_index}_{column}",
                        "metric": column,
                        "period": period,
                        "value": float(value),
                        "unit": _metric_unit(column),
                        "grain": "summary",
                        "intent": _intent_alignment_score(column, message),
                        "completeness": 1.0,
                        "reliability": 0.95,
                        "period_compatibility": 1.0 if period != "unknown_period" else 0.55,
                        "provenance": EvidenceProvenance(
                            stepIndex=step_index,
                            columnRefs=[column],
                            timeWindow=period,
                            aggregationType="single_row_metric",
                        ),
                    }
                )

                prior_value, prior_column = _paired_prior_value(row, column)
                if prior_value is None:
                    continue
                abs_delta = float(value) - float(prior_value)
                pct_delta = (abs_delta / float(prior_value) * 100.0) if float(prior_value) != 0 else None
                raw_comparisons.append(
                    {
                        "id": f"cmp_s{step_index}_{column}",
                        "metric": column,
                        "priorPeriod": prior_period,
                        "currentPeriod": current_period,
                        "priorValue": float(prior_value),
                        "currentValue": float(value),
                        "absDelta": abs_delta,
                        "pctDelta": pct_delta,
                        "compatibilityReason": "current/prior values paired from one-row summary columns.",
                        "intent": _intent_alignment_score(column, message),
                        "completeness": 1.0,
                        "reliability": 0.9,
                        "period_compatibility": 1.0 if prior_period != current_period else 0.6,
                        "provenance": [
                            EvidenceProvenance(
                                stepIndex=step_index,
                                columnRefs=[column, prior_column] if prior_column else [column],
                                timeWindow=f"{prior_period} -> {current_period}",
                                aggregationType="single_row_paired_columns",
                            )
                        ],
                    }
                )

            for metric_root, entries in periodized_metrics.items():
                if len(entries) < 2:
                    continue
                ordered_entries = sorted(entries, key=lambda item: _period_token_sort_key(item[0]))
                prior_period_token, prior_value, prior_column = ordered_entries[-2]
                current_period_token, current_value, current_column = ordered_entries[-1]
                if prior_period_token == current_period_token:
                    continue
                abs_delta = current_value - prior_value
                pct_delta = (abs_delta / prior_value * 100.0) if prior_value != 0 else None
                raw_comparisons.append(
                    {
                        "id": f"cmp_s{step_index}_{metric_root}_{prior_period_token}_{current_period_token}",
                        "metric": metric_root,
                        "priorPeriod": _period_token_label(prior_period_token),
                        "currentPeriod": _period_token_label(current_period_token),
                        "priorValue": prior_value,
                        "currentValue": current_value,
                        "absDelta": abs_delta,
                        "pctDelta": pct_delta,
                        "compatibilityReason": "Paired metric-family columns with explicit period tokens in one-row output.",
                        "intent": _intent_alignment_score(metric_root, message),
                        "completeness": 1.0,
                        "reliability": 0.9,
                        "period_compatibility": 1.0,
                        "provenance": [
                            EvidenceProvenance(
                                stepIndex=step_index,
                                columnRefs=[prior_column, current_column],
                                timeWindow=f"{_period_token_label(prior_period_token)} -> {_period_token_label(current_period_token)}",
                                aggregationType="single_row_periodized_columns",
                            )
                        ],
                    }
                )

            single_row_steps.append(
                {
                    "stepIndex": step_index,
                    "period": period,
                    "metrics": metrics_for_step,
                }
            )
            continue

        dimension_col, prior_col, current_col, change_col = _comparison_columns(profile, message)
        if not dimension_col or not (change_col or (prior_col and current_col)):
            continue
        for row_index, row in enumerate(rows[: max_comparisons * 2], start=1):
            metric_label = str(row.get(dimension_col, f"segment_{row_index}")).strip() or f"segment_{row_index}"
            prior = _to_float(row.get(prior_col)) if prior_col else None
            current = _to_float(row.get(current_col)) if current_col else None
            delta = _to_float(row.get(change_col)) if change_col else None
            if delta is None and prior is not None and current is not None:
                delta = current - prior
            if delta is None or prior is None or current is None:
                continue
            pct_delta = (delta / prior * 100.0) if prior not in {0.0, None} else None
            raw_comparisons.append(
                {
                    "id": f"cmp_s{step_index}_{row_index}",
                    "metric": metric_label,
                    "priorPeriod": prior_col or "prior",
                    "currentPeriod": current_col or "current",
                    "priorValue": float(prior),
                    "currentValue": float(current),
                    "absDelta": float(delta),
                    "pctDelta": float(pct_delta) if pct_delta is not None else None,
                    "compatibilityReason": "current/prior pairing inferred from comparison-style columns in one step output.",
                    "intent": _intent_alignment_score(metric_label, message),
                    "completeness": 1.0,
                    "reliability": 0.9,
                    "period_compatibility": 1.0,
                    "provenance": [
                        EvidenceProvenance(
                            stepIndex=step_index,
                            columnRefs=[column for column in [dimension_col, prior_col, current_col, change_col] if column],
                            timeWindow="",
                            aggregationType="comparison_row",
                        )
                    ],
                }
            )

    if len(single_row_steps) >= 2:
        ordered_steps = sorted(
            single_row_steps,
            key=lambda item: _period_sort_key(str(item["period"]), int(item["stepIndex"])),
        )
        for index in range(1, len(ordered_steps)):
            prior_step = ordered_steps[index - 1]
            current_step = ordered_steps[index]
            common_metrics = sorted(set(prior_step["metrics"].keys()).intersection(set(current_step["metrics"].keys())))
            for metric in common_metrics:
                prior_value = float(prior_step["metrics"][metric])
                current_value = float(current_step["metrics"][metric])
                abs_delta = current_value - prior_value
                pct_delta = (abs_delta / prior_value * 100.0) if prior_value != 0 else None
                raw_comparisons.append(
                    {
                        "id": f"cmp_s{prior_step['stepIndex']}_s{current_step['stepIndex']}_{metric}",
                        "metric": metric,
                        "priorPeriod": str(prior_step["period"]),
                        "currentPeriod": str(current_step["period"]),
                        "priorValue": prior_value,
                        "currentValue": current_value,
                        "absDelta": abs_delta,
                        "pctDelta": pct_delta,
                        "compatibilityReason": "metric appears in adjacent single-row period summaries with matching column names.",
                        "intent": _intent_alignment_score(metric, message),
                        "completeness": 1.0,
                        "reliability": 0.9 if prior_step["period"] != "unknown_period" and current_step["period"] != "unknown_period" else 0.75,
                        "period_compatibility": 1.0 if prior_step["period"] != current_step["period"] else 0.6,
                        "provenance": [
                            EvidenceProvenance(
                                stepIndex=int(prior_step["stepIndex"]),
                                columnRefs=[metric],
                                timeWindow=str(prior_step["period"]),
                                aggregationType="cross_step_single_row_pair",
                            ),
                            EvidenceProvenance(
                                stepIndex=int(current_step["stepIndex"]),
                                columnRefs=[metric],
                                timeWindow=str(current_step["period"]),
                                aggregationType="cross_step_single_row_pair",
                            ),
                        ],
                    }
                )

    max_fact_abs = max((abs(float(item["value"])) for item in raw_facts), default=1.0)
    max_cmp_abs = max((abs(float(item["absDelta"])) for item in raw_comparisons), default=1.0)

    facts: list[FactSignal] = []
    for item in raw_facts:
        magnitude = min(1.0, abs(float(item["value"])) / max_fact_abs) if max_fact_abs > 0 else 0.0
        score, driver = _salience_score(
            intent=float(item["intent"]),
            magnitude=magnitude,
            completeness=float(item["completeness"]),
            reliability=float(item["reliability"]),
            period_compatibility=float(item["period_compatibility"]),
        )
        support = _support_status(reliability=float(item["reliability"]), completeness=float(item["completeness"]))
        facts.append(
            FactSignal(
                id=str(item["id"]),
                metric=str(item["metric"]),
                period=str(item["period"]),
                value=float(item["value"]),
                unit=cast(Literal["currency", "number", "percent"], item["unit"]),
                grain=str(item.get("grain", "")),
                supportStatus=support,
                salienceScore=round(float(score), 6),
                salienceDriver=driver,
                provenance=item["provenance"],
            )
        )

    comparisons: list[ComparisonSignal] = []
    dedupe_ids: set[tuple[str, str, str]] = set()
    for item in raw_comparisons:
        key = (str(item["metric"]).lower(), str(item["priorPeriod"]), str(item["currentPeriod"]))
        if key in dedupe_ids:
            continue
        dedupe_ids.add(key)
        magnitude = min(1.0, abs(float(item["absDelta"])) / max_cmp_abs) if max_cmp_abs > 0 else 0.0
        score, driver = _salience_score(
            intent=float(item["intent"]),
            magnitude=magnitude,
            completeness=float(item["completeness"]),
            reliability=float(item["reliability"]),
            period_compatibility=float(item["period_compatibility"]),
        )
        support = _support_status(reliability=float(item["reliability"]), completeness=float(item["completeness"]))
        comparisons.append(
            ComparisonSignal(
                id=str(item["id"]),
                metric=str(item["metric"]),
                priorPeriod=str(item["priorPeriod"]),
                currentPeriod=str(item["currentPeriod"]),
                priorValue=float(item["priorValue"]),
                currentValue=float(item["currentValue"]),
                absDelta=float(item["absDelta"]),
                pctDelta=float(item["pctDelta"]) if item.get("pctDelta") is not None else None,
                compatibilityReason=str(item.get("compatibilityReason", "")),
                supportStatus=support,
                salienceScore=round(float(score), 6),
                salienceDriver=driver,
                provenance=item.get("provenance", []),
            )
        )

    ranked_facts = sorted(facts, key=lambda item: item.salienceScore, reverse=True)[:max_facts]
    ranked_comparisons = sorted(comparisons, key=lambda item: item.salienceScore, reverse=True)[:max_comparisons]
    for rank, item in enumerate(ranked_facts, start=1):
        item.salienceRank = rank
    for rank, item in enumerate(ranked_comparisons, start=1):
        item.salienceRank = rank
    return ranked_facts, ranked_comparisons
