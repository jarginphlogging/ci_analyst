from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.sandbox.sandbox_sca_service import app


def test_sandbox_cortex_query_endpoint(tmp_path: Path) -> None:
    db_path = str(tmp_path / "cortex_sandbox.db")

    original_path = settings.sandbox_sqlite_path
    original_key = settings.sandbox_cortex_api_key
    try:
        object.__setattr__(settings, "sandbox_sqlite_path", db_path)
        object.__setattr__(settings, "sandbox_cortex_api_key", "test-key")
        client = TestClient(app)
        response = client.post(
            "/api/v2/cortex/analyst/query",
            headers={"Authorization": "Bearer test-key"},
            json={"sql": "SELECT transaction_state, SUM(spend) AS spend_total FROM cia_sales_insights_cortex GROUP BY transaction_state LIMIT 3"},
        )
    finally:
        object.__setattr__(settings, "sandbox_sqlite_path", original_path)
        object.__setattr__(settings, "sandbox_cortex_api_key", original_key)

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("rows"), list)
    assert payload.get("rowCount") == len(payload["rows"])


def test_sandbox_cortex_message_provider_error_and_history(tmp_path: Path) -> None:
    db_path = str(tmp_path / "cortex_sandbox.db")

    original_path = settings.sandbox_sqlite_path
    original_key = settings.sandbox_cortex_api_key
    original_anthropic_key = settings.anthropic_api_key
    try:
        object.__setattr__(settings, "sandbox_sqlite_path", db_path)
        object.__setattr__(settings, "sandbox_cortex_api_key", "test-key")
        object.__setattr__(settings, "anthropic_api_key", None)
        client = TestClient(app)

        first_response = client.post(
            "/api/v2/cortex/analyst/message",
            headers={"Authorization": "Bearer test-key"},
            json={"conversationId": "conv-1", "message": "help"},
        )
        assert first_response.status_code == 502
        assert "SQL generation provider error" in str(first_response.json().get("detail", ""))

        answer_response = client.post(
            "/api/v2/cortex/analyst/message",
            headers={"Authorization": "Bearer test-key"},
            json={"conversationId": "conv-1", "message": "Show spend by state for Q4 2025"},
        )
        assert answer_response.status_code == 502
        assert "SQL generation provider error" in str(answer_response.json().get("detail", ""))

        history_response = client.get(
            "/api/v2/cortex/analyst/history/conv-1",
            headers={"Authorization": "Bearer test-key"},
        )
        assert history_response.status_code == 200
        history_payload = history_response.json()
        assert len(history_payload["history"]) >= 2
    finally:
        object.__setattr__(settings, "sandbox_sqlite_path", original_path)
        object.__setattr__(settings, "sandbox_cortex_api_key", original_key)
        object.__setattr__(settings, "anthropic_api_key", original_anthropic_key)


def test_sandbox_cortex_message_total_sales_last_month_returns_provider_error_when_generation_unavailable(tmp_path: Path) -> None:
    db_path = str(tmp_path / "cortex_sandbox.db")

    original_path = settings.sandbox_sqlite_path
    original_key = settings.sandbox_cortex_api_key
    original_anthropic_key = settings.anthropic_api_key
    try:
        object.__setattr__(settings, "sandbox_sqlite_path", db_path)
        object.__setattr__(settings, "sandbox_cortex_api_key", "test-key")
        object.__setattr__(settings, "anthropic_api_key", None)
        client = TestClient(app)

        response = client.post(
            "/api/v2/cortex/analyst/message",
            headers={"Authorization": "Bearer test-key"},
            json={
                "conversationId": "conv-total-month",
                "message": "Calculate the total sales for last month. Return the aggregate sales amount for the complete prior calendar month.",
            },
        )

        assert response.status_code == 502
        assert "SQL generation provider error" in str(response.json().get("detail", ""))
    finally:
        object.__setattr__(settings, "sandbox_sqlite_path", original_path)
        object.__setattr__(settings, "sandbox_cortex_api_key", original_key)
        object.__setattr__(settings, "anthropic_api_key", original_anthropic_key)
