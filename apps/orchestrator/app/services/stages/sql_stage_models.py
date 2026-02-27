from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config import settings
from app.models import QueryPlanStep

OUT_OF_DOMAIN_MESSAGE = "I can only answer questions about Customer Insights."
TOO_COMPLEX_MESSAGE = "Your request is too complex, please simplify it and try again."
MAX_SQL_ATTEMPTS = max(1, settings.sql_max_attempts)


@dataclass(frozen=True)
class GeneratedStep:
    index: int
    step: QueryPlanStep
    provider: Literal["analyst", "llm"]
    status: Literal["sql_ready", "clarification", "technical_failure", "not_relevant"]
    sql: str | None
    rationale: str
    assumptions: list[str]
    clarification_question: str
    technical_error: str
    not_relevant_reason: str
    attempted_sql: str | None = None
    rows: list[dict[str, Any]] | None = None


class SqlGenerationBlockedError(RuntimeError):
    def __init__(
        self,
        *,
        stop_reason: Literal["clarification", "technical_failure", "not_relevant"],
        user_message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(user_message)
        self.stop_reason = stop_reason
        self.user_message = user_message
        self.detail = detail or {}


@dataclass(frozen=True)
class ExecutionDispatch:
    target_label: str
    parallel_capable: bool
