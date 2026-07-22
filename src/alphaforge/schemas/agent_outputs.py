from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from alphaforge.schemas.backtest import BacktestResult, SmokeTestResult
from alphaforge.schemas.manifests import LeanEnvironmentManifest
from alphaforge.schemas.optimisation import OptimizationConstraints
from alphaforge.schemas.strategy_spec import (
    CandidateType,
    StrategyLogic,
    StrategySpec,
    StrictModel,
)

MetricName = Literal[
    "cagr",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "annual_volatility",
    "turnover",
    "total_fees",
]
RouteType = Literal["traditional", "ml", "hybrid"]


class MetricComparison(StrictModel):
    metric: MetricName
    objective: Literal["higher", "lower"]
    user_value: float
    best_strategy_id: str
    best_run_id: str
    best_value: float
    user_gap: float


class EvidenceSummary(StrictModel):
    evidence_run_ids: tuple[str, ...] = Field(min_length=5, max_length=5)
    comparisons: tuple[MetricComparison, ...] = Field(min_length=7, max_length=7)
    reference_strategies: tuple["ReferenceStrategyEvidence", ...] = Field(
        min_length=5, max_length=5
    )


class ReferenceStrategyEvidence(StrictModel):
    strategy_role: Literal["user", "baseline_b1", "baseline_b2", "baseline_b3", "baseline_b4"]
    strategy_spec: StrategySpec
    backtest_result: BacktestResult
    semantic_sha256: str


class ExecutionChanges(StrictModel):
    top_k: int | None = Field(default=None, ge=1, le=10)
    target_gross: float | None = Field(default=None, ge=0.25, le=0.95)
    regime_filter: Literal["none", "benchmark_sma"] | None = None
    regime_lookback_days: int | None = Field(default=None, ge=50, le=300)

    @model_validator(mode="after")
    def regime_fields_are_consistent(self) -> "ExecutionChanges":
        if self.regime_filter is None and self.regime_lookback_days is not None:
            raise ValueError("regime_lookback_days requires regime_filter")
        if self.regime_filter == "none" and self.regime_lookback_days is not None:
            raise ValueError("regime_filter=none forbids regime_lookback_days")
        if self.regime_filter == "benchmark_sma" and self.regime_lookback_days is None:
            raise ValueError("benchmark_sma requires regime_lookback_days")
        return self


class RiskChanges(StrictModel):
    """No risk-policy changes are permitted in the first contract version."""


class CandidateDesign(StrictModel):
    candidate_type: RouteType
    logic: StrategyLogic
    execution_changes: ExecutionChanges
    risk_changes: RiskChanges
    design_reasons: tuple[str, ...] = Field(min_length=1)
    expected_tradeoffs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def route_matches_logic(self) -> "CandidateDesign":
        if self.logic.kind != self.candidate_type:
            raise ValueError("candidate_type must match logic.kind")
        return self


class DesignRequest(StrictModel):
    optimization_id: str
    candidate_type: RouteType
    round_number: int = Field(ge=1, le=3)
    parent_spec: StrategySpec
    constraints: OptimizationConstraints
    evidence_summary: EvidenceSummary
    prior_attempts: tuple["PriorDesignAttempt", ...] = ()


class PriorDesignAttempt(StrictModel):
    round_number: int = Field(ge=1, le=3)
    candidate_type: RouteType
    strategy_spec: StrategySpec
    semantic_sha256: str
    state: str
    backtest_result: BacktestResult | None = None


class BuiltCandidate(StrictModel):
    design: CandidateDesign
    spec: StrategySpec
    changed_paths: tuple[str, ...]


class StrategyCompilationRequest(StrictModel):
    strategy_spec: StrategySpec
    spec_sha256: str
    lean_environment: LeanEnvironmentManifest
    allowed_qc_api: tuple[str, ...] = Field(min_length=1)
    template_version: str
    template_sha256: str
    semantics_version: Literal["qc_semantics_v1"] = "qc_semantics_v1"


class CodeRegion(StrictModel):
    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_sha256: str


class GeneratedCode(StrictModel):
    strategy_id: str
    language: Literal["python"] = "python"
    entry_file: Literal["main.py"] = "main.py"
    source: str
    source_sha256: str
    spec_sha256: str
    used_qc_api: tuple[str, ...]
    assumptions: tuple[str, ...]
    compiler_metadata: dict[str, str]
    template_version: str
    template_sha256: str
    compiler_version: str
    compiler_sha256: str
    semantics_version: Literal["qc_semantics_v1"]
    regions: tuple[CodeRegion, ...] = Field(min_length=1)


class CodeValidationResult(StrictModel):
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    observed_qc_api: tuple[str, ...] = ()


class CodeRiskFinding(StrictModel):
    code: str
    severity: Literal["warning", "blocking"]
    category: Literal[
        "spec_drift",
        "position_sizing",
        "order_lifecycle",
        "indicator_readiness",
        "lookahead",
        "ml_leakage",
        "exposure",
        "execution",
    ]
    code_location: str
    evidence: str
    risk: str
    required_correction: str


class CodeRiskReviewRequest(StrictModel):
    strategy_spec: StrategySpec
    generated_code: GeneratedCode
    static_validation: CodeValidationResult
    lean_environment: LeanEnvironmentManifest


class CodeRiskReview(StrictModel):
    strategy_id: str
    reviewed_source_sha256: str
    spec_sha256: str
    verdict: Literal["approve", "changes_required", "reject"]
    findings: tuple[CodeRiskFinding, ...] = ()

    @model_validator(mode="after")
    def verdict_matches_findings(self) -> "CodeRiskReview":
        blocking = any(finding.severity == "blocking" for finding in self.findings)
        if self.verdict == "approve" and blocking:
            raise ValueError("approve cannot include blocking findings")
        if self.verdict == "changes_required" and not blocking:
            raise ValueError("changes_required needs at least one blocking finding")
        return self


class RouteOutcome(StrictModel):
    round_number: int = Field(ge=1, le=3)
    candidate_type: RouteType
    state: Literal[
        "rejected_by_design",
        "rejected_by_spec",
        "rejected_by_code_validation",
        "rejected_by_code_risk",
        "rejected_by_smoke_test",
        "rejected_by_backtest",
        "duplicate_of_reference",
        "backtested_not_selected",
        "selected",
    ]
    strategy_spec: StrategySpec | None = None
    changed_paths: tuple[str, ...] = ()
    backtest_result: BacktestResult | None = None
    failure_reasons: tuple[str, ...] = ()


class PostBacktestAnalysisRequest(StrictModel):
    optimization_id: str
    parent_spec: StrategySpec
    evidence: tuple[BacktestResult, ...] = Field(min_length=5, max_length=5)
    route_outcomes: tuple[RouteOutcome, ...] = Field(min_length=3, max_length=9)


class MetricValue(StrictModel):
    strategy_id: str
    run_id: str
    value: float


class MetricAnalysis(StrictModel):
    metric: MetricName
    values: tuple[MetricValue, ...] = Field(min_length=1)
    best_strategy_id: str
    interpretation: str


class CandidateAssessment(StrictModel):
    strategy_id: str
    strengths: tuple[str, ...] = Field(min_length=1)
    weaknesses: tuple[str, ...] = Field(min_length=1)
    tradeoffs: tuple[str, ...] = Field(min_length=1)
    evidence_run_ids: tuple[str, ...] = Field(min_length=1)


class PostBacktestAnalysis(StrictModel):
    metric_analysis: tuple[MetricAnalysis, ...] = Field(min_length=7, max_length=7)
    candidate_assessments: tuple[CandidateAssessment, ...]
    recommended_strategy_ids: tuple[str, ...]
    no_robust_improvement: bool
    summary: str

    @model_validator(mode="after")
    def covers_every_metric_once(self) -> "PostBacktestAnalysis":
        expected = {
            "cagr",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
            "annual_volatility",
            "turnover",
            "total_fees",
        }
        observed = {analysis.metric for analysis in self.metric_analysis}
        if observed != expected or len(observed) != len(self.metric_analysis):
            raise ValueError("metric_analysis must contain each required metric exactly once")
        return self


class SelectionCheck(StrictModel):
    name: Literal[
        "pipeline_eligible",
        "result_completed",
        "min_sharpe_improvement",
        "max_drawdown_deterioration",
        "max_drawdown_limit",
    ]
    passed: bool
    actual: float | str
    required: float | str


class CandidateSelection(StrictModel):
    strategy_id: str
    eligible: bool
    checks: tuple[SelectionCheck, ...]


class SelectionResult(StrictModel):
    selected_strategy_id: str | None
    eligible_strategy_ids: tuple[str, ...]
    candidates: tuple[CandidateSelection, ...]
    no_robust_improvement: bool


class CandidateRun(StrictModel):
    round_number: int = Field(default=1, ge=1, le=3)
    candidate_type: RouteType
    state: Literal[
        "rejected_by_design",
        "rejected_by_spec",
        "rejected_by_code_validation",
        "rejected_by_code_risk",
        "rejected_by_smoke_test",
        "rejected_by_backtest",
        "duplicate_of_reference",
        "backtested_not_selected",
        "selected",
    ]
    design: CandidateDesign | None = None
    strategy_spec: StrategySpec | None = None
    changed_paths: tuple[str, ...] = ()
    generated_code: GeneratedCode | None = None
    code_validation: CodeValidationResult | None = None
    code_risk_review: CodeRiskReview | None = None
    smoke_test: SmokeTestResult | None = None
    backtest_result: BacktestResult | None = None
    failure_reasons: tuple[str, ...] = ()
    semantic_sha256: str | None = None
    duplicate_of_strategy_id: str | None = None


class AuditEvent(StrictModel):
    sequence: int
    stage: str
    subject_id: str
    outcome: str
    detail: str


class TemplateCapabilityRecord(StrictModel):
    candidate_type: RouteType
    status: Literal["rendered", "cannot_implement", "template_error", "duplicate"]
    reasons: tuple[str, ...] = ()


class TemplateCapabilityReport(StrictModel):
    template_version: str
    records: tuple[TemplateCapabilityRecord, ...] = Field(min_length=3, max_length=9)

    @property
    def rendered_count(self) -> int:
        return sum(record.status == "rendered" for record in self.records)


class OptimizationResult(StrictModel):
    optimization_id: str
    status: Literal["completed", "failed"]
    evidence_summary: EvidenceSummary
    candidates: tuple[CandidateRun, ...] = Field(min_length=3, max_length=9)
    post_backtest_analysis: PostBacktestAnalysis | None
    selection: SelectionResult
    analysis_error: str | None = None
    audit_log: tuple[AuditEvent, ...]
    template_capability_report: TemplateCapabilityReport

    @property
    def selected_types(self) -> tuple[CandidateType, ...]:
        return tuple(c.candidate_type for c in self.candidates if c.state == "selected")
