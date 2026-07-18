from __future__ import annotations

from alphaforge.schemas.agent_outputs import (
    CandidateRun,
    CandidateSelection,
    SelectionCheck,
    SelectionResult,
)
from alphaforge.schemas.backtest import BacktestResult
from alphaforge.schemas.optimisation import OptimizationConstraints


class CandidateSelector:
    def select(
        self,
        *,
        evidence: tuple[BacktestResult, ...],
        candidates: tuple[CandidateRun, ...],
        constraints: OptimizationConstraints,
    ) -> SelectionResult:
        parent = next(result for result in evidence if result.strategy_role == "user")
        if parent.metrics is None:
            raise ValueError("parent result must contain metrics")

        selections: list[CandidateSelection] = []
        eligible_runs: list[CandidateRun] = []
        for candidate in candidates:
            result = candidate.backtest_result
            pipeline_eligible = candidate.state == "backtested_not_selected"
            completed = result is not None and result.status == "completed" and result.metrics is not None
            checks: list[SelectionCheck] = [
                SelectionCheck(
                    name="pipeline_eligible",
                    passed=pipeline_eligible,
                    actual=candidate.state,
                    required="backtested_not_selected",
                ),
                SelectionCheck(
                    name="result_completed",
                    passed=completed,
                    actual=result.status if result else "missing",
                    required="completed",
                )
            ]
            if completed and result is not None and result.metrics is not None and candidate.strategy_spec is not None:
                sharpe_delta = result.metrics.sharpe_ratio - parent.metrics.sharpe_ratio
                drawdown_delta = result.metrics.max_drawdown - parent.metrics.max_drawdown
                checks.extend(
                    (
                        SelectionCheck(
                            name="min_sharpe_improvement",
                            passed=sharpe_delta >= constraints.min_sharpe_improvement,
                            actual=sharpe_delta,
                            required=constraints.min_sharpe_improvement,
                        ),
                        SelectionCheck(
                            name="max_drawdown_deterioration",
                            passed=drawdown_delta <= constraints.max_drawdown_deterioration,
                            actual=drawdown_delta,
                            required=constraints.max_drawdown_deterioration,
                        ),
                        SelectionCheck(
                            name="max_drawdown_limit",
                            passed=result.metrics.max_drawdown <= candidate.strategy_spec.risk.max_drawdown_limit,
                            actual=result.metrics.max_drawdown,
                            required=candidate.strategy_spec.risk.max_drawdown_limit,
                        ),
                    )
                )
            eligible = pipeline_eligible and completed and all(check.passed for check in checks)
            if eligible:
                eligible_runs.append(candidate)
            strategy_id = (
                candidate.strategy_spec.strategy_id
                if candidate.strategy_spec is not None
                else f"unbuilt_{candidate.candidate_type}"
            )
            selections.append(
                CandidateSelection(strategy_id=strategy_id, eligible=eligible, checks=tuple(checks))
            )

        eligible_runs.sort(
            key=lambda candidate: (
                candidate.backtest_result.metrics.sharpe_ratio,  # type: ignore[union-attr]
                -candidate.backtest_result.metrics.max_drawdown,  # type: ignore[union-attr]
                -candidate.backtest_result.metrics.total_fees,  # type: ignore[union-attr]
            ),
            reverse=True,
        )
        selected = eligible_runs[0].strategy_spec.strategy_id if eligible_runs else None  # type: ignore[union-attr]
        return SelectionResult(
            selected_strategy_id=selected,
            eligible_strategy_ids=tuple(
                candidate.strategy_spec.strategy_id for candidate in eligible_runs  # type: ignore[union-attr]
            ),
            candidates=tuple(selections),
            no_robust_improvement=selected is None,
        )
