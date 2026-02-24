from __future__ import annotations

import json

from app.models import SqlExecutionResult
from app.services.stages.data_summarizer_stage import DataSummarizerStage


def test_data_summarizer_builds_rich_table_summary() -> None:
    results = [
        SqlExecutionResult(
            sql="SELECT transaction_state, current_value, prior_value, change_value, resp_date FROM t",
            rows=[
                {
                    "transaction_state": "TX",
                    "current_value": 120.0,
                    "prior_value": 100.0,
                    "change_value": 20.0,
                    "resp_date": "2025-10-01",
                },
                {
                    "transaction_state": "FL",
                    "current_value": 95.0,
                    "prior_value": 110.0,
                    "change_value": -15.0,
                    "resp_date": "2025-10-02",
                },
                {
                    "transaction_state": "CA",
                    "current_value": 140.0,
                    "prior_value": 118.0,
                    "change_value": 22.0,
                    "resp_date": "2025-10-03",
                },
            ],
            rowCount=3,
        )
    ]

    stage = DataSummarizerStage()
    summaries = stage.summarize_tables(results=results, message="Compare by state")

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["rowCount"] == 3
    assert "numericStats" in summary
    assert "current_value" in summary["numericStats"]
    assert summary["numericStats"]["current_value"]["max"] == 140.0
    assert "dateStats" in summary
    assert "resp_date" in summary["dateStats"]
    assert "categoricalStats" in summary
    assert "transaction_state" in summary["categoricalStats"]
    assert "comparisonSignals" in summary
    assert "largestChangeRow" in summary["comparisonSignals"]


def test_data_summarizer_prompt_payload_is_structured_and_bounded() -> None:
    rows = [
        {"segment": f"s{i}", "value": float(i), "resp_date": f"2025-10-{(i % 28) + 1:02d}"}
        for i in range(1, 25)
    ]
    results = [SqlExecutionResult(sql="SELECT ...", rows=rows, rowCount=len(rows))]

    stage = DataSummarizerStage()
    prompt_payload = stage.summarize_for_prompt(results=results, message="Show trend")
    parsed = json.loads(prompt_payload)

    assert "portfolioSummary" in parsed
    assert parsed["portfolioSummary"]["tableCount"] == 1
    assert parsed["portfolioSummary"]["totalRows"] == 24
    table_summary = parsed["tableSummaries"][0]
    assert len(table_summary["sampleRows"]) <= 3
