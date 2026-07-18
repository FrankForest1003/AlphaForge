from __future__ import annotations

from alphaforge.schemas.agent_outputs import (
    BaselineAnalysis,
    CandidateDecision,
    CandidateProposal,
    GeneratedCode,
    MetricObservation,
    RiskReview,
)
from alphaforge.schemas.backtest import BacktestMetrics, BacktestResult
from alphaforge.schemas.optimisation import OptimizationRequest
from alphaforge.schemas.strategy_spec import (
    CandidateType,
    HybridLogic,
    MLLogic,
    StrategySpec,
    TraditionalLogic,
)


class MockAgentProvider:
    """Deterministic Agent simulator with no model, network, or hidden market evidence."""

    def analyze(self, request: OptimizationRequest) -> BaselineAnalysis:
        complete = [r for r in request.evidence if r.metrics is not None]
        best_sharpe = max(complete, key=lambda r: r.metrics.sharpe_ratio)  # type: ignore[union-attr]
        lowest_drawdown = min(complete, key=lambda r: r.metrics.max_drawdown)  # type: ignore[union-attr]
        return BaselineAnalysis(
            evidence_run_ids=tuple(r.run_id for r in complete),
            observations=(
                MetricObservation(
                    metric="sharpe_ratio",
                    strategy_id=best_sharpe.strategy_id,
                    value=best_sharpe.metrics.sharpe_ratio,  # type: ignore[union-attr]
                    interpretation="highest validation Sharpe among supplied evidence",
                ),
                MetricObservation(
                    metric="max_drawdown",
                    strategy_id=lowest_drawdown.strategy_id,
                    value=lowest_drawdown.metrics.max_drawdown,  # type: ignore[union-attr]
                    interpretation="lowest validation drawdown among supplied evidence",
                ),
            ),
            design_priorities=(
                "preserve the approved universe and comparison period",
                "improve risk-adjusted return without breaching the drawdown limit",
                "keep traditional, ML and hybrid signal sources distinct",
            ),
        )

    def propose(
        self,
        route: CandidateType,
        request: OptimizationRequest,
        analysis: BaselineAnalysis,
    ) -> CandidateProposal:
        if route not in ("traditional", "ml", "hybrid"):
            raise ValueError(f"unsupported candidate route: {route}")

        parent = request.parent_spec
        traditional = TraditionalLogic(signal="momentum_rank", lookback_days=126)
        ml = MLLogic(
            model="gradient_boosting",
            task="relative_alpha_regression",
            training_window_days=756,
            prediction_horizon_days=21,
            feature_set_version="features_v0_mock",
            random_seed=42,
        )
        logic = {
            "traditional": traditional,
            "ml": ml,
            "hybrid": HybridLogic(traditional=traditional, ml=ml, traditional_weight=0.5),
        }[route]

        spec = parent.model_copy(
            update={
                "strategy_id": f"{request.optimization_id}_{route}_r1",
                "parent_strategy_id": parent.strategy_id,
                "candidate_type": route,
                "logic": logic,
            }
        )
        spec = StrategySpec.model_validate(spec.model_dump())
        return CandidateProposal(
            candidate_type=route,
            spec=spec,
            changed_paths=("/candidate_type", "/logic"),
            design_reasons=(
                f"construct an isolated {route} route from the same parent and evidence",
                "use only validation metrics referenced by the baseline analysis",
            ),
            expected_tradeoffs=(
                "the mock result is a plumbing test and is not evidence of investment performance",
            ),
        )

    def review_risk(self, proposal: CandidateProposal) -> RiskReview:
        reasons: list[str] = []
        spec = proposal.spec
        if spec.risk.max_position_weight > 0.35:
            reasons.append("POSITION_CAP_EXCEEDED")
        if not spec.risk.long_only or spec.risk.max_leverage != 1.0:
            reasons.append("DIRECTION_OR_LEVERAGE_VIOLATION")
        return RiskReview(
            verdict="reject" if reasons else "approve",
            reason_codes=tuple(reasons),
            reviewed_strategy_id=spec.strategy_id,
        )

    def decide(
        self,
        request: OptimizationRequest,
        proposal: CandidateProposal,
        result: BacktestResult,
    ) -> CandidateDecision:
        parent_result = next(r for r in request.evidence if r.strategy_role == "user")
        if result.metrics is None or parent_result.metrics is None:
            return CandidateDecision(verdict="reject", reason_codes=("MISSING_METRICS",))

        reasons: list[str] = []
        if result.metrics.sharpe_ratio < (
            parent_result.metrics.sharpe_ratio + request.constraints.min_sharpe_improvement
        ):
            reasons.append("INSUFFICIENT_SHARPE_IMPROVEMENT")
        if result.metrics.max_drawdown > (
            parent_result.metrics.max_drawdown
            + request.constraints.max_drawdown_deterioration
        ):
            reasons.append("DRAWDOWN_DETERIORATION")
        if result.metrics.max_drawdown > proposal.spec.risk.max_drawdown_limit:
            reasons.append("DRAWDOWN_LIMIT_BREACH")
        return CandidateDecision(
            verdict="reject" if reasons else "accept",
            reason_codes=tuple(reasons) if reasons else ("VALIDATION_THRESHOLDS_MET",),
        )


class MockBacktestProvider:
    """Fixed fixtures used only to prove orchestration and decision paths."""

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

    def run(self, spec: StrategySpec, code: GeneratedCode) -> BacktestResult:
        if code.strategy_id != spec.strategy_id:
            raise ValueError("generated code strategy_id does not match spec")
        metrics = self._METRICS[spec.candidate_type]
        return BacktestResult(
            run_id=f"mock-run-{spec.strategy_id}",
            strategy_id=spec.strategy_id,
            strategy_role="candidate",
            status="completed",
            dataset_split="validation",
            provider="mock-backtest-v1",
            metrics=metrics,
            warnings=("SIMULATED_RESULT_NOT_FINANCIAL_EVIDENCE",),
        )
