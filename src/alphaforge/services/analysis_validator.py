from __future__ import annotations

import math

from alphaforge.schemas.agent_outputs import PostBacktestAnalysis, PostBacktestAnalysisRequest


def validate_post_backtest_analysis(
    request: PostBacktestAnalysisRequest,
    analysis: PostBacktestAnalysis,
) -> tuple[str, ...]:
    """Verify that model-written comparisons reproduce the supplied evidence exactly."""

    successful = tuple(
        outcome.backtest_result
        for outcome in request.route_outcomes
        if outcome.backtest_result is not None
        and outcome.backtest_result.status == "completed"
        and outcome.backtest_result.metrics is not None
    )
    results = tuple(request.evidence) + successful
    expected_ids = {result.strategy_id for result in results}
    expected_candidate_ids = {result.strategy_id for result in successful}
    expected_runs = {result.run_id for result in results}
    errors: list[str] = []

    for metric_analysis in analysis.metric_analysis:
        expected = {
            (result.strategy_id, result.run_id): getattr(result.metrics, metric_analysis.metric)
            for result in results
            if result.metrics is not None
        }
        observed = {
            (value.strategy_id, value.run_id): value.value
            for value in metric_analysis.values
        }
        if observed.keys() != expected.keys() or any(
            not math.isclose(observed[key], expected[key], rel_tol=1e-9, abs_tol=1e-12)
            for key in expected
        ):
            errors.append(f"METRIC_VALUES_MISMATCH:{metric_analysis.metric}")
        objective = "higher" if metric_analysis.metric in {
            "cagr",
            "sharpe_ratio",
            "sortino_ratio",
        } else "lower"
        chooser = max if objective == "higher" else min
        expected_best = chooser(
            results,
            key=lambda result: getattr(result.metrics, metric_analysis.metric),
        ).strategy_id
        if metric_analysis.best_strategy_id != expected_best:
            errors.append(f"BEST_STRATEGY_MISMATCH:{metric_analysis.metric}")

    assessment_ids = {assessment.strategy_id for assessment in analysis.candidate_assessments}
    if assessment_ids != expected_candidate_ids:
        errors.append("CANDIDATE_ASSESSMENTS_MISMATCH")
    for assessment in analysis.candidate_assessments:
        if not set(assessment.evidence_run_ids).issubset(expected_runs):
            errors.append(f"UNKNOWN_EVIDENCE_RUN:{assessment.strategy_id}")
    if not set(analysis.recommended_strategy_ids).issubset(expected_candidate_ids):
        errors.append("UNKNOWN_RECOMMENDED_STRATEGY")
    observed_ids = {
        value.strategy_id
        for metric_analysis in analysis.metric_analysis
        for value in metric_analysis.values
    }
    if expected_ids != observed_ids:
        errors.append("ANALYSIS_STRATEGY_COVERAGE_MISMATCH")
    return tuple(dict.fromkeys(errors))
