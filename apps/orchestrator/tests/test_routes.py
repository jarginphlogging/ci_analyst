from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_turn_endpoint() -> None:
    response = client.post(
        "/v1/chat/turn",
        json={"sessionId": str(uuid4()), "message": "What changed in charge-off risk this quarter?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["answer"]
    assert len(payload["response"]["dataTables"]) >= 1


def test_stream_endpoint() -> None:
    response = client.post(
        "/v1/chat/stream",
        json={"sessionId": str(uuid4()), "message": "Where are fraud losses accelerating?"},
    )

    assert response.status_code == 200
    assert '"type": "answer_delta"' in response.text or '"type":"answer_delta"' in response.text
    assert '"type": "done"' in response.text or '"type":"done"' in response.text
