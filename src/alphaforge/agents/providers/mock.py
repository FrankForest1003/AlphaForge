from __future__ import annotations

import hashlib

from alphaforge.codegen.code_validator import DEFAULT_ALLOWED_QC_API
from alphaforge.schemas.agent_outputs import (
    CandidateAssessment,
    CandidateDesign,
    CodeRiskReview,
    CodeRiskReviewRequest,
    DesignRequest,
    ExecutionChanges,
    GeneratedCode,
    MetricAnalysis,
    MetricValue,
    PostBacktestAnalysis,
    PostBacktestAnalysisRequest,
    QCCodeGenerationRequest,
    RepairRequest,
    RiskChanges,
)
from alphaforge.schemas.backtest import BacktestMetrics, BacktestResult, SmokeTestResult
from alphaforge.schemas.strategy_spec import HybridLogic, MLLogic, TraditionalLogic
from alphaforge.strategy_spec.versioning import strategy_spec_digest


class MockStrategyDesigner:
    def design(self, request: DesignRequest) -> CandidateDesign:
        traditional = TraditionalLogic(signal="momentum_rank", lookback_days=126)
        ml = MLLogic(
            model="gradient_boosting",
            task="relative_alpha_regression",
            training_window_days=756,
            prediction_horizon_days=21,
            feature_set_version="features_v1",
            random_seed=42,
        )
        logic = {
            "traditional": traditional,
            "ml": ml,
            "hybrid": HybridLogic(traditional=traditional, ml=ml, traditional_weight=0.5),
        }[request.candidate_type]
        return CandidateDesign(
            candidate_type=request.candidate_type,
            logic=logic,
            execution_changes=ExecutionChanges(top_k=3),
            risk_changes=RiskChanges(),
            design_reasons=(f"create a distinct {request.candidate_type} candidate",),
            expected_tradeoffs=("candidate complexity may increase implementation risk",),
        )


class MockQCCodeAgent:
    def generate(self, request: QCCodeGenerationRequest) -> GeneratedCode:
        spec = request.strategy_spec
        symbols = ", ".join(repr(symbol) for symbol in spec.universe.symbols)
        source = (
            "from AlgorithmImports import *\n\n"
            "class AlphaForgeAlgorithm(QCAlgorithm):\n"
            "    def Initialize(self):\n"
            f"        self.SetStartDate({spec.execution.start_date.year}, {spec.execution.start_date.month}, {spec.execution.start_date.day})\n"
            f"        self.SetEndDate({spec.execution.end_date.year}, {spec.execution.end_date.month}, {spec.execution.end_date.day})\n"
            f"        self.SetCash({spec.execution.initial_cash})\n"
            f"        for ticker in [{symbols}]:\n"
            "            self.AddEquity(ticker, Resolution.Daily)\n"
        )
        used = (
            "QCAlgorithm",
            "SetStartDate",
            "SetEndDate",
            "SetCash",
            "AddEquity",
            "Resolution.Daily",
        )
        return GeneratedCode(
            strategy_id=spec.strategy_id,
            source=source,
            source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            spec_sha256=request.spec_sha256,
            used_qc_api=used,
            assumptions=("daily adjusted equity data are available",),
            generator_metadata={"agent": "mock_qc_code", "template_version": request.template_version},
        )


class MockCodeRiskAgent:
    def review(self, request: CodeRiskReviewRequest) -> CodeRiskReview:
        return CodeRiskReview(
            strategy_id=request.strategy_spec.strategy_id,
            reviewed_source_sha256=request.generated_code.source_sha256,
            spec_sha256=request.generated_code.spec_sha256,
            verdict="approve",
            findings=(),
        )


class MockRepairAgent:
    def __init__(self) -> None:
        self.generator = MockQCCodeAgent()

    def repair(self, request: RepairRequest) -> GeneratedCode:
        return self.generator.generate(
            QCCodeGenerationRequest(
                strategy_spec=request.strategy_spec,
                spec_sha256=strategy_spec_digest(request.strategy_spec),
                lean_environment=request.lean_environment,
                allowed_qc_api=DEFAULT_ALLOWED_QC_API,
                template_version="qc_template_v1",
            )
        )


class MockPostBacktestAnalysisAgent:
    OBJECTIVES = {
        "cagr": "higher",
        "sharpe_ratio": "higher",
        "sortino_ratio": "higher",
        "max_drawdown": "lower",
        "annual_volatility": "lower",
        "turnover": "lower",
        "total_fees": "lower",
    }

    def analyze(self, request: PostBacktestAnalysisRequest) -> PostBacktestAnalysis:
        completed = [
            outcome.backtest_result
            for outcome in request.route_outcomes
            if outcome.backtest_result is not None and outcome.backtest_result.metrics is not None
        ]
        all_results = [*request.evidence, *completed]
        metric_analysis: list[MetricAnalysis] = []
        for metric, objective in self.OBJECTIVES.items():
            available = [result for result in all_results if result.metrics is not None]
            best = sorted(
                available,
                key=lambda result: getattr(result.metrics, metric),
                reverse=objective == "higher",
            )[0]
            metric_analysis.append(
                MetricAnalysis(
                    metric=metric,
                    values=tuple(
                        MetricValue(
                            strategy_id=result.strategy_id,
                            run_id=result.run_id,
                            value=float(getattr(result.metrics, metric)),
                        )
                        for result in available
                    ),
                    best_strategy_id=best.strategy_id,
                    interpretation=f"{best.strategy_id} has the {objective}-preferred {metric}",
                )
            )
        assessments = tuple(
            CandidateAssessment(
                strategy_id=result.strategy_id,
                strengths=("completed the controlled validation run",),
                weaknesses=("requires robustness testing before any research conclusion",),
                tradeoffs=("return, risk, turnover, and fees must be considered together",),
                evidence_run_ids=(result.run_id,),
            )
            for result in completed
        )
        ranking = tuple(
            result.strategy_id
            for result in sorted(
                completed,
                key=lambda result: result.metrics.sharpe_ratio,  # type: ignore[union-attr]
                reverse=True,
            )
        )
        return PostBacktestAnalysis(
            metric_analysis=tuple(metric_analysis),
            candidate_assessments=assessments,
            recommended_strategy_ids=ranking,
            no_robust_improvement=not completed,
            summary="All completed candidates were compared using one normalized evidence set.",
        )


class MockBacktestProvider:
    _METRICS = {
        "traditional": BacktestMetrics(
            cagr=0.13,
            sharpe_ratio=1.08,
            sortino_ratio=1.42,
            max_drawdown=0.17,
            annual_volatility=0.15,
            turnover=0.70,
            total_fees=110.0,
        ),
        "ml": BacktestMetrics(
            cagr=0.15,
            sharpe_ratio=1.02,
            sortino_ratio=1.28,
            max_drawdown=0.23,
            annual_volatility=0.21,
            turnover=1.35,
            total_fees=230.0,
        ),
        "hybrid": BacktestMetrics(
            cagr=0.14,
            sharpe_ratio=1.16,
            sortino_ratio=1.51,
            max_drawdown=0.16,
            annual_volatility=0.16,
            turnover=0.95,
            total_fees=160.0,
        ),
    }

    def smoke_test(self, spec, code) -> SmokeTestResult:
        return SmokeTestResult(
            strategy_id=spec.strategy_id,
            status="passed",
            diagnostics=(),
            provider="mock_lean_smoke",
        )

    def run(self, spec, code) -> BacktestResult:
        return BacktestResult(
            run_id=f"mock-run-{spec.strategy_id}",
            strategy_id=spec.strategy_id,
            strategy_role="candidate",
            status="completed",
            dataset_split="validation",
            provider="mock_backtest",
            metrics=self._METRICS[spec.candidate_type],
            warnings=("SIMULATED_RESULT_NOT_FINANCIAL_EVIDENCE",),
        )
