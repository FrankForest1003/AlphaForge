from __future__ import annotations

from typing import Protocol

from alphaforge.schemas.agent_outputs import (
    CandidateDesign,
    CodeRiskReview,
    CodeRiskReviewRequest,
    DesignRequest,
    GeneratedCode,
    PostBacktestAnalysis,
    PostBacktestAnalysisRequest,
    StrategyCompilationRequest,
)
from alphaforge.schemas.backtest import BacktestResult, SmokeTestResult
from alphaforge.schemas.strategy_spec import StrategySpec


class StrategyDesigner(Protocol):
    def design(self, request: DesignRequest) -> CandidateDesign: ...


class StrategyCompiler(Protocol):
    def compile(self, request: StrategyCompilationRequest) -> GeneratedCode: ...


class CodeRiskAgent(Protocol):
    def review(self, request: CodeRiskReviewRequest) -> CodeRiskReview: ...


class PostBacktestAnalysisAgent(Protocol):
    def analyze(self, request: PostBacktestAnalysisRequest) -> PostBacktestAnalysis: ...


class BacktestProvider(Protocol):
    def smoke_test(self, spec: StrategySpec, code: GeneratedCode) -> SmokeTestResult: ...

    def run(self, spec: StrategySpec, code: GeneratedCode) -> BacktestResult: ...
