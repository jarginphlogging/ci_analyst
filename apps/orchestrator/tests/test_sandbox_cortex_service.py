from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.sandbox.cortex_service import app


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


def test_sandbox_cortex_message_clarification_and_history(tmp_path: Path) -> None:
    db_path = str(tmp_path / "cortex_sandbox.db")

    original_path = settings.sandbox_sqlite_path
    original_key = settings.sandbox_cortex_api_key
    original_anthropic_key = settings.anthropic_api_key
    try:
        object.__setattr__(settings, "sandbox_sqlite_path", db_path)
        object.__setattr__(settings, "sandbox_cortex_api_key", "test-key")
        object.__setattr__(settings, "anthropic_api_key", None)
        client = TestClient(app)

        vague_response = client.post(
            "/api/v2/cortex/analyst/message",
            headers={"Authorization": "Bearer test-key"},
            json={"conversationId": "conv-1", "message": "help"},
        )
        assert vague_response.status_code == 200
        vague_payload = vague_response.json()
        assert vague_payload["type"] == "clarification"
        assert vague_payload["clarificationQuestion"]
        assert isinstance(vague_payload["rows"], list)

        answer_response = client.post(
            "/api/v2/cortex/analyst/message",
            headers={"Authorization": "Bearer test-key"},
            json={"conversationId": "conv-1", "message": "Show spend by state for Q4 2025"},
        )
        assert answer_response.status_code == 200
        answer_payload = answer_response.json()
        assert answer_payload["type"] == "answer"
        assert answer_payload["sql"]
        assert isinstance(answer_payload["rows"], list)

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
