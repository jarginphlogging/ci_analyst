from __future__ import annotations

from app.evaluation.inline_checks_v2_1 import (
    check_answer_sanity,
    check_pii,
    check_plan_sanity,
    check_result_sanity,
    check_sql_syntax,
    check_validation_contract,
    redact_pii,
)


def test_check_plan_sanity_passes_for_valid_plan() -> None:
    passed, reason = check_plan_sanity(
        [
            {"id": "step_1", "goal": "Compute spend by state."},
            {"id": "step_2", "goal": "Rank top states."},
        ]
    )
    assert passed is True
    assert reason == "passed"


def test_check_sql_syntax_rejects_non_select() -> None:
    passed, reason = check_sql_syntax("DELETE FROM cia_sales_insights_cortex")
    assert passed is False
    assert "SELECT/WITH" in reason


def test_check_sql_syntax_handles_comment_only_input() -> None:
    passed, reason = check_sql_syntax("-- only a comment")
    assert passed is False
    assert "SELECT or WITH" in reason


def test_check_result_sanity_rejects_empty_rows() -> None:
    passed, reason = check_result_sanity([], 0, max_rows=10_000)
    assert passed is False
    assert "row count is zero" in reason


def test_check_result_sanity_rejects_oversized_cell() -> None:
    huge = "x" * 101
    passed, reason = check_result_sanity([{"payload": huge}], 1, max_rows=10_000, max_cell_bytes=100)
    assert passed is False
    assert "cell larger" in reason


def test_validation_contract_requires_checks() -> None:
    passed, reason = check_validation_contract(True, [])
    assert passed is False
    assert "empty" in reason


def test_pii_detection_and_redaction() -> None:
    text = "Customer SSN is 123-45-6789 and account 123456789012"
    pii_pass, _ = check_pii(text)
    redacted = redact_pii(text)
    assert pii_pass is False
    assert "123-45-6789" not in redacted
    assert "[REDACTED]" in redacted


def test_pii_card_detection_uses_luhn_validation() -> None:
    card_like_but_invalid = "Payment attempt id 1234 5678 9012 3456"
    pii_pass_invalid, _ = check_pii(card_like_but_invalid)
    assert pii_pass_invalid is True

    valid_test_card = "Card used: 4111 1111 1111 1111"
    pii_pass_valid, _ = check_pii(valid_test_card)
    assert pii_pass_valid is False


def test_answer_sanity_rejects_known_error_pattern() -> None:
    passed, reason = check_answer_sanity("SQL generation blocked due to warehouse parser error.")
    assert passed is False
    assert "error pattern" in reason
