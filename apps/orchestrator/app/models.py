from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JsonValue = Optional[Union[str, int, float, bool]]


class ChatTurnRequest(BaseModel):
    sessionId: Optional[UUID] = None
    message: str
    role: Optional[str] = None
    explicitFilters: Optional[dict[str, list[str]]] = None


class TraceStep(BaseModel):
    id: str
    title: str
    summary: str
    status: Literal["done", "running", "blocked"]
    sql: Optional[str] = None
    qualityChecks: Optional[list[str]] = None


class MetricPoint(BaseModel):
    label: str
    value: float
    delta: float
    unit: Literal["pct", "bps", "usd", "count"]


class EvidenceRow(BaseModel):
    segment: str
    prior: float
    current: float
    changeBps: float
    contribution: float


class Insight(BaseModel):
    id: str
    title: str
    detail: str
    importance: Literal["high", "medium"]


class DataTable(BaseModel):
    id: str
    name: str
    columns: list[str]
    rows: list[dict[str, JsonValue]]
    rowCount: int
    description: Optional[str] = None
    sourceSql: Optional[str] = None


class AnalysisArtifact(BaseModel):
    id: str
    kind: Literal[
        "ranking_breakdown",
        "comparison_breakdown",
        "delta_breakdown",
        "trend_breakdown",
        "distribution_breakdown",
    ]
    title: str
    description: Optional[str] = None
    columns: list[str]
    rows: list[dict[str, JsonValue]]
    dimensionKey: Optional[str] = None
    valueKey: Optional[str] = None
    timeKey: Optional[str] = None
    expectedGrain: Optional[str] = None
    detectedGrain: Optional[str] = None


class AgentResponse(BaseModel):
    answer: str
    confidence: Literal["high", "medium", "low"]
    whyItMatters: str
    metrics: list[MetricPoint]
    evidence: list[EvidenceRow]
    insights: list[Insight]
    suggestedQuestions: list[str]
    assumptions: list[str]
    trace: list[TraceStep]
    dataTables: list[DataTable] = Field(default_factory=list)
    artifacts: list[AnalysisArtifact] = Field(default_factory=list)


class TurnResult(BaseModel):
    turnId: str
    createdAt: str
    response: AgentResponse


class QueryPlanStep(BaseModel):
    id: str
    goal: str


class SqlExecutionResult(BaseModel):
    sql: str
    rows: list[dict[str, JsonValue]]
    rowCount: int


class ValidationResult(BaseModel):
    passed: bool
    checks: list[str]


class StreamResult(BaseModel):
    events: list[dict[str, Any]]
    turn: TurnResult


class ErrorResponse(BaseModel):
    error: str


class StatusEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["status"]
    message: str


class AnswerDeltaEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["answer_delta"]
    delta: str


class ResponseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["response"]
    response: AgentResponse
    phase: Optional[Literal["draft", "final"]] = None


class DoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["done"]


class ErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"]
    message: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
