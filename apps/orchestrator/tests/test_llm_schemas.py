from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.llm_schemas import SqlGenerationResponsePayload


def test_sql_generation_payload_treats_blank_optional_fields_as_none() -> None:
    payload = SqlGenerationResponsePayload.model_validate(
        {
            "generationType": "sql_ready",
            "sql": "SELECT 1",
            "rationale": "ok",
            "clarificationQuestion": "",
            "clarificationKind": "",
            "notRelevantReason": "",
            "assumptions": [],
        }
    )

    assert payload.clarificationQuestion is None
    assert payload.clarificationKind is None
    assert payload.notRelevantReason is None


def test_sql_generation_payload_still_rejects_missing_required_sql() -> None:
    with pytest.raises(ValidationError):
        SqlGenerationResponsePayload.model_validate(
            {
                "generationType": "sql_ready",
                "sql": "",
                "rationale": "missing sql",
                "clarificationQuestion": "",
                "clarificationKind": "",
                "notRelevantReason": "",
                "assumptions": [],
            }
        )
