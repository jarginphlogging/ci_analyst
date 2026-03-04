from __future__ import annotations

from app.services.stages.sql_state_machine import normalize_retry_feedback


def test_normalize_retry_feedback_strips_none_like_failed_sql_values() -> None:
    normalized = normalize_retry_feedback(
        [
            {
                "phase": "sql_generation_blocked",
                "attempt": 1,
                "stepId": "step_1",
                "provider": "analyst",
                "errorCode": "generation_provider_error",
                "errorCategory": "generation",
                "error": "empty sql",
                "failedSql": "None",
            },
            {
                "phase": "sql_generation_blocked",
                "attempt": 2,
                "stepId": "step_1",
                "provider": "analyst",
                "errorCode": "generation_provider_error",
                "errorCategory": "generation",
                "error": "still empty sql",
                "failedSql": None,
            },
        ]
    )
    assert len(normalized) == 2
    assert normalized[0]["failedSql"] is None
    assert normalized[1]["failedSql"] is None
