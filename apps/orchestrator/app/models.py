from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JsonValue = Optional[Union[str, int, float, bool]]
ArtifactKind = Literal[
    "ranking_breakdown",
    "comparison_breakdown",
    "delta_breakdown",
    "trend_breakdown",
    "distribution_breakdown",
]
VisualType = Literal["trend", "ranking", "comparison", "distribution", "snapshot", "table"]
DisplayType = Literal["inline", "table", "chart"]
ChartType = Literal["line", "bar", "stacked_bar", "stacked_area", "grouped_bar"]
TableStyle = Literal["simple", "ranked", "comparison"]
SalienceDriver = Literal["intent", "magnitude", "completeness", "reliability", "period_compatibility"]
SupportStatus = Literal["strong", "moderate", "weak"]
EvidenceStatus = Literal["sufficient", "limited", "insufficient"]
TimeUnit = Literal["day", "week", "month", "quarter", "year"]


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
    runtimeMs: Optional[float] = None
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
    evidenceRefs: list["EvidenceReference"] = Field(default_factory=list)
    salienceRank: Optional[int] = None
    salienceScore: Optional[float] = None
    salienceDriver: Optional[SalienceDriver] = None
    supportStatus: Optional[SupportStatus] = None


class SummaryCard(BaseModel):
    label: str
    value: str
    detail: str = ""


class EvidenceReference(BaseModel):
    refType: Literal["fact", "comparison"]
    refId: str


class EvidenceProvenance(BaseModel):
    stepIndex: int
    columnRefs: list[str] = Field(default_factory=list)
    timeWindow: str = ""
    aggregationType: str = ""


class FactSignal(BaseModel):
    id: str
    metric: str
    period: str
    value: float
    unit: Literal["currency", "number", "percent"] = "number"
    grain: str = ""
    supportStatus: SupportStatus = "moderate"
    salienceScore: float = 0.0
    salienceRank: Optional[int] = None
    salienceDriver: Optional[SalienceDriver] = None
    provenance: EvidenceProvenance


class ComparisonSignal(BaseModel):
    id: str
    metric: str
    priorPeriod: str
    currentPeriod: str
    priorValue: float
    currentValue: float
    absDelta: float
    pctDelta: Optional[float] = None
    compatibilityReason: str = ""
    supportStatus: SupportStatus = "moderate"
    salienceScore: float = 0.0
    salienceRank: Optional[int] = None
    salienceDriver: Optional[SalienceDriver] = None
    provenance: list[EvidenceProvenance] = Field(default_factory=list)


class ClaimSupport(BaseModel):
    claimId: str
    claimType: Literal["fact", "comparison"]
    supportStatus: SupportStatus
    reason: str = ""


class SubtaskStatus(BaseModel):
    id: str
    status: EvidenceStatus
    reason: str = ""


class PrimaryVisual(BaseModel):
    title: str
    description: str = ""
    visualType: VisualType = "snapshot"
    artifactKind: Optional[ArtifactKind] = None


class PresentationIntent(BaseModel):
    displayType: DisplayType
    chartType: Optional[ChartType] = None
    tableStyle: Optional[TableStyle] = None
    rationale: str = ""
    rankingObjectives: list[str] = Field(default_factory=list)


class TemporalScope(BaseModel):
    kind: Literal["relative_last_n"] = "relative_last_n"
    unit: TimeUnit
    count: int = Field(default=1, ge=1, le=120)
    anchor: Literal["latest_available"] = "latest_available"
    granularity: Optional[TimeUnit] = None


class ChartConfig(BaseModel):
    type: ChartType
    x: str
    y: Union[str, list[str]]
    series: Optional[str] = None
    xLabel: str = ""
    yLabel: str = ""
    yFormat: Literal["currency", "number", "percent"] = "number"


class TableColumnConfig(BaseModel):
    key: str
    label: str
    format: Literal["currency", "number", "percent", "date", "string"]
    align: Literal["left", "right"] = "left"


class TableConfig(BaseModel):
    style: TableStyle = "simple"
    columns: list[TableColumnConfig] = Field(default_factory=list)
    sortBy: Optional[str] = None
    sortDir: Optional[Literal["asc", "desc"]] = None
    showRank: bool = False
    comparisonMode: Optional[Literal["baseline", "pairwise", "index"]] = None
    comparisonKeys: list[str] = Field(default_factory=list)
    baselineKey: Optional[str] = None
    deltaPolicy: Optional[Literal["abs", "pct", "both"]] = None
    maxComparandsBeforeChartSwitch: Optional[int] = None


class AgentResponse(BaseModel):
    answer: str
    confidence: Literal["high", "medium", "low"]
    confidenceReason: str = ""
    whyItMatters: str
    presentationIntent: Optional[PresentationIntent] = None
    chartConfig: Optional[ChartConfig] = None
    tableConfig: Optional[TableConfig] = None
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
    facts: list[FactSignal] = Field(default_factory=list)
    comparisons: list[ComparisonSignal] = Field(default_factory=list)
    evidenceStatus: EvidenceStatus = "insufficient"
    evidenceEmptyReason: str = ""
    subtaskStatus: list[SubtaskStatus] = Field(default_factory=list)
    claimSupport: list[ClaimSupport] = Field(default_factory=list)
    headline: str = ""
    headlineEvidenceRefs: list[EvidenceReference] = Field(default_factory=list)
    periodStart: Optional[str] = None
    periodEnd: Optional[str] = None
    periodLabel: Optional[str] = None


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
    requestedClaimModes: list[str] = Field(default_factory=list)
    supportedClaims: list[dict[str, Any]] = Field(default_factory=list)
    unsupportedClaims: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)
    dataQuality: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[FactSignal] = Field(default_factory=list)
    comparisons: list[ComparisonSignal] = Field(default_factory=list)
    evidenceStatus: EvidenceStatus = "insufficient"
    evidenceEmptyReason: str = ""
    subtaskStatus: list[SubtaskStatus] = Field(default_factory=list)
    interpretationNotes: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    headline: str = ""
    headlineEvidenceRefs: list[EvidenceReference] = Field(default_factory=list)


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


class DoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["done"]


class ErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"]
    message: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
