from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JsonValue = Optional[Union[str, int, float, bool]]
AnalysisType = Literal[
    "trend_over_time",
    "ranking_top_n_bottom_n",
    "comparison",
    "composition_breakdown",
    "aggregation_summary_stats",
    "point_in_time_snapshot",
    "period_over_period_change",
    "anomaly_outlier_detection",
    "drill_down_root_cause",
    "correlation_relationship",
    "cohort_analysis",
    "distribution_histogram",
    "forecasting_projection",
    "threshold_filter_segmentation",
    "cumulative_running_total",
    "rate_ratio_efficiency",
]
ArtifactKind = Literal[
    "ranking_breakdown",
    "comparison_breakdown",
    "delta_breakdown",
    "trend_breakdown",
    "distribution_breakdown",
]
VisualType = Literal["trend", "ranking", "comparison", "distribution", "snapshot", "table"]


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
    stageInput: Optional[dict[str, Any]] = None
    stageOutput: Optional[dict[str, Any]] = None


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
    kind: ArtifactKind
    title: str
    description: Optional[str] = None
    columns: list[str]
    rows: list[dict[str, JsonValue]]
    dimensionKey: Optional[str] = None
    valueKey: Optional[str] = None
    timeKey: Optional[str] = None
    expectedGrain: Optional[str] = None
    detectedGrain: Optional[str] = None


class SummaryCard(BaseModel):
    label: str
    value: str
    detail: str = ""


class PrimaryVisual(BaseModel):
    title: str
    description: str = ""
    visualType: VisualType = "snapshot"
    artifactKind: Optional[ArtifactKind] = None


class AgentResponse(BaseModel):
    answer: str
    confidence: Literal["high", "medium", "low"]
    confidenceReason: str = ""
    whyItMatters: str
    analysisType: AnalysisType = "aggregation_summary_stats"
    secondaryAnalysisType: Optional[AnalysisType] = None
    metrics: list[MetricPoint]
    evidence: list[EvidenceRow]
    insights: list[Insight]
    suggestedQuestions: list[str]
    assumptions: list[str]
    trace: list[TraceStep]
    summaryCards: list[SummaryCard] = Field(default_factory=list)
    primaryVisual: Optional[PrimaryVisual] = None
    dataTables: list[DataTable] = Field(default_factory=list)
    artifacts: list[AnalysisArtifact] = Field(default_factory=list)


class TurnResult(BaseModel):
    turnId: str
    createdAt: str
    response: AgentResponse


class QueryPlanStep(BaseModel):
    id: str
    goal: str
    dependsOn: list[str] = Field(default_factory=list)
    independent: bool = True


class SynthesisQueryContext(BaseModel):
    originalUserQuery: str
    route: str
    analysisType: AnalysisType = "aggregation_summary_stats"
    secondaryAnalysisType: Optional[AnalysisType] = None


class SynthesisVisualArtifact(BaseModel):
    kind: ArtifactKind
    title: str
    rowCount: int


class SynthesisPlanStep(BaseModel):
    id: str
    goal: str
    dependsOn: list[str] = Field(default_factory=list)
    independent: bool = True


class SynthesisExecutedStep(BaseModel):
    stepIndex: int
    planStep: SynthesisPlanStep
    executedSql: str
    rowCount: int
    tableSummary: dict[str, Any] = Field(default_factory=dict)


class SynthesisPortfolioSummary(BaseModel):
    tableCount: int
    totalRows: int


class SynthesisContextPackage(BaseModel):
    queryContext: SynthesisQueryContext
    plan: list[SynthesisPlanStep] = Field(default_factory=list)
    executedSteps: list[SynthesisExecutedStep] = Field(default_factory=list)
    availableVisualArtifacts: list[SynthesisVisualArtifact] = Field(default_factory=list)
    portfolioSummary: SynthesisPortfolioSummary


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
