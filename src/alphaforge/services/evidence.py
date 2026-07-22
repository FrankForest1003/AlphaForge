from __future__ import annotations

from alphaforge.schemas.agent_outputs import (
    EvidenceSummary,
    MetricComparison,
    MetricName,
    ReferenceStrategyEvidence,
)
from alphaforge.schemas.backtest import BacktestResult
from alphaforge.schemas.strategy_spec import StrategySpec
from alphaforge.strategy_spec.versioning import strategy_semantic_digest


class EvidenceSummarizer:
    OBJECTIVES: dict[MetricName, str] = {
        "cagr": "higher",
        "sharpe_ratio": "higher",
        "sortino_ratio": "higher",
        "max_drawdown": "lower",
        "annual_volatility": "lower",
        "turnover": "lower",
        "total_fees": "lower",
    }

    def summarize(
        self,
        evidence: tuple[BacktestResult, ...],
        reference_specs: tuple[StrategySpec, ...],
    ) -> EvidenceSummary:
        if len(evidence) != 5:
            raise ValueError("exactly five evidence results are required")
        if any(result.metrics is None or result.status != "completed" for result in evidence):
            raise ValueError("all evidence results must be completed with metrics")
        user = next((result for result in evidence if result.strategy_role == "user"), None)
        if user is None or user.metrics is None:
            raise ValueError("user strategy evidence is required")
        specs_by_id = {spec.strategy_id: spec for spec in reference_specs}
        if len(specs_by_id) != 5:
            raise ValueError("exactly five unique reference specs are required")
        missing_specs = sorted(result.strategy_id for result in evidence if result.strategy_id not in specs_by_id)
        if missing_specs:
            raise ValueError(f"reference specs missing for evidence: {missing_specs}")

        comparisons: list[MetricComparison] = []
        for metric, objective in self.OBJECTIVES.items():
            ordered = sorted(
                evidence,
                key=lambda result: getattr(result.metrics, metric),  # type: ignore[arg-type]
                reverse=objective == "higher",
            )
            best = ordered[0]
            best_value = float(getattr(best.metrics, metric))  # type: ignore[arg-type]
            user_value = float(getattr(user.metrics, metric))
            gap = best_value - user_value if objective == "higher" else user_value - best_value
            comparisons.append(
                MetricComparison(
                    metric=metric,
                    objective=objective,
                    user_value=user_value,
                    best_strategy_id=best.strategy_id,
                    best_run_id=best.run_id,
                    best_value=best_value,
                    user_gap=gap,
                )
            )
        return EvidenceSummary(
            evidence_run_ids=tuple(result.run_id for result in evidence),
            comparisons=tuple(comparisons),
            reference_strategies=tuple(
                ReferenceStrategyEvidence(
                    strategy_role=result.strategy_role,
                    strategy_spec=specs_by_id[result.strategy_id],
                    backtest_result=result,
                    semantic_sha256=strategy_semantic_digest(specs_by_id[result.strategy_id]),
                )
                for result in evidence
            ),
        )
