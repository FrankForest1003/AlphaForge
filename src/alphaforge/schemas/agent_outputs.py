from __future__ import annotations

from typing import Literal

from alphaforge.schemas.backtest import BacktestResult
from alphaforge.schemas.strategy_spec import CandidateType, StrategySpec, StrictModel


class MetricObservation(StrictModel):
    metric: str
    strategy_id: str
    value: float
    interpretation: str


class BaselineAnalysis(StrictModel):
    evidence_run_ids: tuple[str, ...]
    observations: tuple[MetricObservation, ...]
    design_priorities: tuple[str, ...]


class CandidateProposal(StrictModel):
    candidate_type: Literal["traditional", "ml", "hybrid"]
    spec: StrategySpec
    changed_paths: tuple[str, ...]
    design_reasons: tuple[str, ...]
    expected_tradeoffs: tuple[str, ...]


class RiskReview(StrictModel):
    verdict: Literal["approve", "reject"]
    reason_codes: tuple[str, ...] = ()
    reviewed_strategy_id: str


class GeneratedCode(StrictModel):
    strategy_id: str
    language: Literal["python"] = "python"
    generator: str
    source: str
    sha256: str
    spec_sha256: str


class CodeValidationResult(StrictModel):
    valid: bool
    errors: tuple[str, ...] = ()


class RepairRequest(StrictModel):
    spec: StrategySpec
    failed_code: GeneratedCode
    validation_errors: tuple[str, ...]
    attempt: int


class CandidateDecision(StrictModel):
    verdict: Literal["accept", "reject"]
    reason_codes: tuple[str, ...]


class CandidateRun(StrictModel):
    candidate_type: Literal["traditional", "ml", "hybrid"]
    state: Literal[
        "accepted",
        "rejected_by_validation",
        "rejected_by_risk",
        "rejected_by_code",
        "rejected_after_backtest",
    ]
    proposal: CandidateProposal
    risk_review: RiskReview | None = None
    generated_code: GeneratedCode | None = None
    code_validation: CodeValidationResult | None = None
    backtest_result: BacktestResult | None = None
    decision: CandidateDecision | None = None
    validation_errors: tuple[str, ...] = ()


class AuditEvent(StrictModel):
    sequence: int
    stage: str
    subject_id: str
    outcome: str
    detail: str


class OptimizationResult(StrictModel):
    optimization_id: str
    status: Literal["completed", "failed"]
    analysis: BaselineAnalysis
    candidates: tuple[CandidateRun, ...]
    audit_log: tuple[AuditEvent, ...]

    @property
    def accepted_types(self) -> tuple[CandidateType, ...]:
        return tuple(c.candidate_type for c in self.candidates if c.state == "accepted")
