from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ChartConfig, PresentationIntent, TableConfig, TemporalScope


class PlannerTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    dependsOn: list[str] = Field(default_factory=list)
    independent: bool = True


class PlannerResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: Literal["in_domain", "out_of_domain", "unclear"]
    relevanceReason: str
    presentationIntent: PresentationIntent
    tooComplex: bool
    temporalScope: Optional[TemporalScope] = None
    tasks: list[PlannerTaskPayload] = Field(default_factory=list)


class SqlGenerationResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generationType: Literal["sql_ready", "clarification", "not_relevant"]
    sql: Optional[str] = None
    rationale: str = ""
    clarificationQuestion: Optional[str] = None
    clarificationKind: Optional[Literal["user_input_required", "technical_failure"]] = None
    notRelevantReason: Optional[str] = None
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("sql", "clarificationQuestion", "clarificationKind", "notRelevantReason", mode="before")
    @classmethod
    def _normalize_optional_blank_strings(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "SqlGenerationResponsePayload":
        if self.generationType == "sql_ready" and not (self.sql or "").strip():
            raise ValueError("sql is required when generationType=sql_ready")
        if self.generationType == "clarification" and not (self.clarificationQuestion or "").strip():
            raise ValueError("clarificationQuestion is required when generationType=clarification")
        if self.generationType == "not_relevant" and not (self.notRelevantReason or "").strip():
            raise ValueError("notRelevantReason is required when generationType=not_relevant")
        return self


class AnalystResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    sql: str = ""
    lightResponse: str = ""
    clarificationQuestion: str = ""
    clarificationKind: str = ""
    notRelevantReason: str = ""
    assumptions: list[str] = Field(default_factory=list)
    rows: Optional[list[dict[str, Any]]] = None
    failedSql: Optional[str] = None
    relevance: str = ""
    relevanceReason: str = ""
    explanation: str = ""
    conversationId: Optional[str] = None
    rowCount: Optional[int] = None

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "AnalystResponsePayload":
        normalized = self.type.strip().lower().replace("-", "_")
        allowed = {
            "sql_ready",
            "answer",
            "sql",
            "clarification",
            "clarify",
            "not_relevant",
            "out_of_domain",
            "irrelevant",
        }
        if normalized not in allowed:
            raise ValueError("type must map to sql_ready, clarification, or not_relevant")

        mapped = normalized
        if mapped in {"answer", "sql"}:
            mapped = "sql_ready"
        elif mapped == "clarify":
            mapped = "clarification"
        elif mapped in {"out_of_domain", "irrelevant"}:
            mapped = "not_relevant"

        if mapped == "sql_ready" and not self.sql.strip():
            raise ValueError("sql is required when type=sql_ready")
        if mapped == "clarification" and not self.clarificationQuestion.strip():
            raise ValueError("clarificationQuestion is required when type=clarification")
        if mapped == "not_relevant" and not (
            self.notRelevantReason.strip() or self.relevanceReason.strip()
        ):
            raise ValueError("notRelevantReason is required when type=not_relevant")
        return self


class SynthesisSummaryCardPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    detail: str = ""


class SynthesisInsightPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str
    importance: Literal["high", "medium"]


class SynthesisResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    whyItMatters: str
    confidence: Literal["high", "medium", "low"]
    confidenceReason: str
    summaryCards: list[SynthesisSummaryCardPayload] = Field(default_factory=list)
    chartConfig: Optional[ChartConfig] = None
    tableConfig: Optional[TableConfig] = None
    insights: list[SynthesisInsightPayload] = Field(default_factory=list)
    suggestedQuestions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
