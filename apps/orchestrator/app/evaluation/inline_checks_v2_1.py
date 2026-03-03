from __future__ import annotations

import re
from typing import Any

import sqlparse

_ERROR_PATTERNS = (
    "i couldn't complete that request",
    "please review the trace for details",
    "result validation failed",
    "sql generation blocked",
)

_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_ACCOUNT_PATTERN = re.compile(r"\b(?:account|acct)[\s:#-]*\d{6,17}\b", re.IGNORECASE)
_CARD_PATTERN = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_MASK = "[REDACTED]"


def _as_text(value: Any) -> str:
    return str(value) if value is not None else ""


def _digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


def _passes_luhn(number: str) -> bool:
    if not number.isdigit() or not (13 <= len(number) <= 19):
        return False
    total = 0
    parity = len(number) % 2
    for index, char in enumerate(number):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def check_plan_sanity(plan: list[dict[str, object]], *, max_steps: int = 5) -> tuple[bool, str]:
    if not isinstance(plan, list):
        return False, "Plan must be a list."
    if not plan:
        return False, "Plan cannot be empty."
    if len(plan) > max_steps:
        return False, f"Plan exceeds max steps ({max_steps})."
    for index, step in enumerate(plan, start=1):
        if not isinstance(step, dict):
            return False, f"Plan step {index} is not an object."
        step_id = _as_text(step.get("id")).strip()
        goal = _as_text(step.get("goal")).strip()
        if not step_id:
            return False, f"Plan step {index} missing id."
        if not goal:
            return False, f"Plan step {index} missing goal."
    return True, "passed"


def check_sql_syntax(sql: str) -> tuple[bool, str]:
    text = _as_text(sql).strip()
    if not text:
        return False, "SQL is empty."
    try:
        parsed = sqlparse.parse(text)
    except Exception:  # noqa: BLE001
        return False, "SQL failed to parse."
    if not parsed:
        return False, "SQL failed to parse."
    first = parsed[0]
    sql_type = (first.get_type() or "UNKNOWN").upper()
    if sql_type not in {"SELECT", "UNKNOWN"}:
        # sqlparse can classify WITH queries as UNKNOWN.
        return False, f"SQL type is {sql_type}, expected SELECT/WITH."
    lowered = text.lower().lstrip()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False, "SQL must start with SELECT or WITH."
    return True, "passed"


def check_result_sanity(
    rows: list[dict[str, object]],
    row_count: int,
    *,
    max_rows: int,
    max_cell_bytes: int = 1_000_000,
) -> tuple[bool, str]:
    if row_count <= 0:
        return False, "SQL result row count is zero."
    if row_count > max_rows:
        return False, f"SQL result row count {row_count} exceeds max {max_rows}."
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        for value in row.values():
            raw = _as_text(value).encode("utf-8", errors="ignore")
            if len(raw) > max_cell_bytes:
                return False, "SQL result contains a cell larger than max allowed size."
    return True, "passed"


def check_validation_contract(passed: bool, checks: list[str]) -> tuple[bool, str]:
    if not isinstance(passed, bool):
        return False, "Validation pass flag must be a boolean."
    if not isinstance(checks, list):
        return False, "Validation checks must be a list."
    if not checks:
        return False, "Validation checks are empty."
    return True, "passed"


def check_answer_sanity(answer: str, *, min_chars: int = 20) -> tuple[bool, str]:
    text = _as_text(answer).strip()
    if not text:
        return False, "Answer is empty."
    if len(text) < min_chars:
        return False, f"Answer is shorter than {min_chars} characters."
    lowered = text.lower()
    if any(pattern in lowered for pattern in _ERROR_PATTERNS):
        return False, "Answer matches known error pattern."
    return True, "passed"


def check_pii(answer: str) -> tuple[bool, str]:
    text = _as_text(answer)
    if _SSN_PATTERN.search(text):
        return False, "Detected SSN pattern."
    if _ACCOUNT_PATTERN.search(text):
        return False, "Detected account number pattern."
    for candidate in _CARD_PATTERN.findall(text):
        digits = _digits_only(candidate)
        if _passes_luhn(digits):
            return False, "Detected card-like number pattern."
    return True, "passed"


def redact_pii(answer: str) -> str:
    text = _as_text(answer)
    redacted = _SSN_PATTERN.sub(_MASK, text)
    redacted = _ACCOUNT_PATTERN.sub(lambda _: f"account {_MASK}", redacted)
    redacted = _CARD_PATTERN.sub(_MASK, redacted)
    return redacted
