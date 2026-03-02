from __future__ import annotations

from app.models import AnalysisType, DataTable
from app.services.presentation_contracts import (
    PRESENTATION_CONTRACTS,
    get_presentation_contract,
    table_fallback_presentation_plan,
    validate_presentation_plan,
)


def test_presentation_contracts_cover_all_analysis_types() -> None:
    all_types: set[AnalysisType] = {
        "trend_over_time",
        "ranking_top_n_bottom_n",
        "comparison",
        "composition_breakdown",
        "aggregation_summary_stats",
        "point_in_time_snapshot",
        "period_over_period_change",
        "anomaly_outlier_detection",
        "drill_down_root_cause",
        "correlation_relationship",
        "cohort_analysis",
        "distribution_histogram",
        "forecasting_projection",
        "threshold_filter_segmentation",
        "cumulative_running_total",
        "rate_ratio_efficiency",
    }
    assert set(PRESENTATION_CONTRACTS.keys()) == all_types
    for analysis_type in all_types:
        contract = get_presentation_contract(analysis_type)
        assert contract.analysis_type == analysis_type
        assert contract.visual_type


def test_validate_presentation_plan_accepts_valid_ranking_plan() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["entity", "rank", "sales"],
            rows=[
                {"entity": "UT", "rank": 1, "sales": 10.0},
                {"entity": "CA", "rank": 2, "sales": 9.0},
            ],
            rowCount=2,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "ranking_top_n_bottom_n",
            "visualType": "ranking",
            "tableId": "sql_step_1",
            "title": "Ranking",
            "scopeLabel": "Calendar year 2025",
            "bindings": {
                "entity_label": "entity",
                "rank_index": "rank",
                "value": "sales",
            },
            "sort": ["rank_index:asc"],
        },
        analysis_type="ranking_top_n_bottom_n",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.visualType == "ranking"
    assert plan.tableId == "sql_step_1"


def test_table_fallback_presentation_plan_uses_first_table() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["value"],
            rows=[{"value": 1.0}],
            rowCount=1,
        )
    ]
    fallback = table_fallback_presentation_plan(
        analysis_type="comparison",
        data_tables=tables,
        reason="missing required bindings",
    )
    assert fallback is not None
    assert fallback.visualType == "table"
    assert fallback.tableId == "sql_step_1"
    assert "missing required bindings" in fallback.notes


def test_validate_presentation_plan_accepts_step_alias_table_id() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["entity", "rank", "sales"],
            rows=[{"entity": "UT", "rank": 1, "sales": 10.0}],
            rowCount=1,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "ranking_top_n_bottom_n",
            "visualType": "ranking",
            "tableId": "step_1",
            "title": "Ranking",
            "scopeLabel": "Calendar year 2025",
            "bindings": {
                "entity_label": "entity",
                "rank_index": "rank",
                "value": "sales",
            },
            "sort": ["rank_index:asc"],
        },
        analysis_type="ranking_top_n_bottom_n",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.tableId == "sql_step_1"


def test_validate_presentation_plan_accepts_numeric_table_id_alias() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["entity", "rank", "sales"],
            rows=[{"entity": "UT", "rank": 1, "sales": 10.0}],
            rowCount=1,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "ranking_top_n_bottom_n",
            "visualType": "ranking",
            "tableId": "1",
            "title": "Ranking",
            "scopeLabel": "Calendar year 2025",
            "bindings": {
                "entity_label": "entity",
                "rank_index": "rank",
                "value": "sales",
            },
            "sort": ["rank_index:asc"],
        },
        analysis_type="ranking_top_n_bottom_n",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.tableId == "sql_step_1"


def test_validate_presentation_plan_accepts_minimal_plan_for_every_analysis_type() -> None:
    def sample_value(binding_type: str) -> object:
        if binding_type == "number":
            return 1.0
        if binding_type == "boolean":
            return True
        if binding_type == "time":
            return "2025-01-01"
        if binding_type == "time_or_number":
            return 1
        return "label"

    for analysis_type, contract in PRESENTATION_CONTRACTS.items():
        row: dict[str, object] = {}
        bindings: dict[str, str] = {}
        for role, expected_type in contract.required_bindings.items():
            column = f"{role}_col"
            row[column] = sample_value(expected_type)
            bindings[role] = column

        tables = [
            DataTable(
                id="sql_step_1",
                name="SQL Step 1 Output",
                columns=list(row.keys()),
                rows=[row],
                rowCount=1,
            )
        ]
        plan, issues = validate_presentation_plan(
            raw_plan={
                "analysisType": analysis_type,
                "visualType": contract.visual_type,
                "tableId": "1",
                "title": "Primary Visual",
                "scopeLabel": "Test Scope",
                "bindings": bindings,
                "sort": contract.default_sort,
            },
            analysis_type=analysis_type,
            data_tables=tables,
        )
        assert issues == [], f"{analysis_type} should validate with minimal contract bindings: {issues}"
        assert plan is not None
        assert plan.visualType == contract.visual_type


def test_validate_presentation_plan_normalizes_rank_binding_when_it_matches_value() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["entity", "total_sales"],
            rows=[
                {"entity": "UT", "total_sales": 49_300_263.48},
                {"entity": "CT", "total_sales": 47_505_087.42},
            ],
            rowCount=2,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "ranking_top_n_bottom_n",
            "visualType": "ranking",
            "tableId": "sql_step_1",
            "title": "Ranking",
            "scopeLabel": "Calendar year 2025",
            "bindings": {
                "entity_label": "entity",
                "rank_index": "total_sales",
                "value": "total_sales",
            },
            "sort": ["rank_index:asc"],
        },
        analysis_type="ranking_top_n_bottom_n",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.bindings["rank_index"] == "__row_index__"


def test_validate_presentation_plan_ignores_invalid_sort_entries() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["entity", "sales"],
            rows=[{"entity": "UT", "sales": 10.0}],
            rowCount=1,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "ranking_top_n_bottom_n",
            "visualType": "ranking",
            "tableId": "sql_step_1",
            "title": "Ranking",
            "scopeLabel": "Calendar year 2025",
            "bindings": {
                "entity_label": "entity",
                "rank_index": "sales",
                "value": "sales",
            },
            "sort": ["category:desc", "rank_index:asc"],
        },
        analysis_type="ranking_top_n_bottom_n",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.sort == ["rank_index:asc"]


def test_validate_presentation_plan_auto_binds_ranking_group_label_and_maps_sort_column() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["entity", "sales", "category"],
            rows=[
                {"entity": "UT", "sales": 10.0, "category": "Top 10"},
                {"entity": "CA", "sales": 5.0, "category": "Bottom 10"},
            ],
            rowCount=2,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "ranking_top_n_bottom_n",
            "visualType": "ranking",
            "tableId": "sql_step_1",
            "title": "Ranking",
            "scopeLabel": "Calendar year 2025",
            "bindings": {
                "entity_label": "entity",
                "rank_index": "sales",
                "value": "sales",
            },
            "sort": ["category:desc", "rank_index:asc"],
        },
        analysis_type="ranking_top_n_bottom_n",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.bindings["group_label"] == "category"
    assert plan.sort == ["group_label:desc", "rank_index:asc"]


def test_validate_presentation_plan_accepts_time_column_for_period_label() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["month", "sales"],
            rows=[
                {"month": "2025-01-01", "sales": 100.0},
                {"month": "2025-02-01", "sales": 105.0},
            ],
            rowCount=2,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "trend_over_time",
            "visualType": "trend",
            "tableId": "sql_step_1",
            "title": "MoM Sales",
            "scopeLabel": "Jan-Dec 2025",
            "bindings": {
                "period_label": "month",
                "period_order": "month",
                "value": "sales",
            },
            "sort": ["period_order:asc"],
        },
        analysis_type="trend_over_time",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.visualType == "trend"


def test_validate_presentation_plan_normalizes_text_rank_index_column() -> None:
    tables = [
        DataTable(
            id="sql_step_1",
            name="SQL Step 1 Output",
            columns=["state", "category", "total_sales"],
            rows=[
                {"state": "UT", "category": "Top 10", "total_sales": 49_300_263.48},
                {"state": "CA", "category": "Bottom 10", "total_sales": 27_271_062.54},
            ],
            rowCount=2,
        )
    ]
    plan, issues = validate_presentation_plan(
        raw_plan={
            "analysisType": "ranking_top_n_bottom_n",
            "visualType": "ranking",
            "tableId": "sql_step_1",
            "title": "State ranking",
            "scopeLabel": "Calendar year 2025",
            "bindings": {
                "entity_label": "state",
                "rank_index": "category",
                "value": "total_sales",
            },
            "sort": ["rank_index:asc"],
        },
        analysis_type="ranking_top_n_bottom_n",
        data_tables=tables,
    )
    assert issues == []
    assert plan is not None
    assert plan.bindings["rank_index"] == "__row_index__"
