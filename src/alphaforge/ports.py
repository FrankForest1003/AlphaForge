from __future__ import annotations

from typing import Protocol

from alphaforge.schemas.agent_outputs import (
    BaselineAnalysis,
    CandidateDecision,
    CandidateProposal,
    GeneratedCode,
    RepairRequest,
    RiskReview,
)
from alphaforge.schemas.backtest import BacktestResult
from alphaforge.schemas.optimisation import OptimizationRequest
from alphaforge.schemas.strategy_spec import CandidateType, StrategySpec


class AgentProvider(Protocol):
    """Semantic Agent boundary; implementations may be LLM-backed or deterministic."""

    def analyze(self, request: OptimizationRequest) -> BaselineAnalysis: ...

    def propose(
        self,
        route: CandidateType,
        request: OptimizationRequest,
        analysis: BaselineAnalysis,
    ) -> CandidateProposal: ...

    def review_risk(self, proposal: CandidateProposal) -> RiskReview: ...

    def decide(
        self,
        request: OptimizationRequest,
        proposal: CandidateProposal,
        result: BacktestResult,
    ) -> CandidateDecision: ...


class CodeGenerationProvider(Protocol):
    def generate(self, spec: StrategySpec) -> GeneratedCode: ...


class BacktestProvider(Protocol):
    """Execution boundary shared by mock, Local LEAN and optional cloud providers."""

    def run(self, spec: StrategySpec, code: GeneratedCode) -> BacktestResult: ...


class RepairProvider(Protocol):
    """Implementation repair boundary; the immutable input spec is authoritative."""

    def repair(self, request: RepairRequest) -> GeneratedCode: ...
