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
