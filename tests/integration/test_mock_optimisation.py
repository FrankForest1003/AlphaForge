from __future__ import annotations

import hashlib
import threading

import pytest

from alphaforge.agents.orchestrator import OptimisationOrchestrator
from alphaforge.agents.providers.mock import (
    MockBacktestProvider,
    MockCodeRiskAgent,
    MockPostBacktestAnalysisAgent,
    MockStrategyDesigner,
)
from alphaforge.codegen.compiler import DeterministicStrategyCompiler
from alphaforge.demo import build_demo_environment, build_demo_request
from alphaforge.schemas.agent_outputs import CodeRiskFinding, CodeRiskReview
from alphaforge.schemas.agent_outputs import CandidateDesign, ExecutionChanges, RiskChanges
from alphaforge.schemas.backtest import BacktestResult, SmokeTestResult
from alphaforge.schemas.backtest import BacktestMetrics
from alphaforge.schemas.strategy_spec import HybridLogic
from alphaforge.services.analysis_validator import validate_post_backtest_analysis
from alphaforge.services.candidate_selector import CandidateSelector
from alphaforge.services.resumer import OptimizationResumer


class CountingAnalysisAgent(MockPostBacktestAnalysisAgent):
    def __init__(self) -> None:
        self.calls = 0
        self.request = None

    def analyze(self, request):
        self.calls += 1
        self.request = request
        result = super().analyze(request)
        return result.model_copy(
            update={"recommended_strategy_ids": tuple(reversed(result.recommended_strategy_ids))}
        )


class RecordingCompiler(DeterministicStrategyCompiler):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def compile(self, request):
        self.events.append((request.strategy_spec.candidate_type, "strategy_compilation"))
        return super().compile(request)


class RecordingRiskAgent(MockCodeRiskAgent):
    def __init__(self, events):
        self.events = events
        self.requests = []

    def review(self, request):
        self.events.append((request.strategy_spec.candidate_type, "code_risk"))
        self.requests.append(request)
        assert "backtest_result" not in type(request).model_fields
        return super().review(request)


class RecordingBacktestProvider(MockBacktestProvider):
    def __init__(self, events=None):
        self.events = events
        self.smoke_calls = 0
        self.run_calls = 0

    def smoke_test(self, spec, code):
        self.smoke_calls += 1
        if self.events is not None:
            self.events.append((spec.candidate_type, "smoke_test"))
        return super().smoke_test(spec, code)

    def run(self, spec, code):
        self.run_calls += 1
        if self.events is not None:
            self.events.append((spec.candidate_type, "backtest"))
        return super().run(spec, code)


def build_orchestrator(*, analysis_agent=None, compiler=None, risk_agent=None, backtest=None):
    return OptimisationOrchestrator(
        designer=MockStrategyDesigner(),
        strategy_compiler=compiler,
        code_risk_agent=risk_agent or MockCodeRiskAgent(),
        backtest_provider=backtest or MockBacktestProvider(),
        analysis_agent=analysis_agent or MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )


def test_closed_loop_uses_one_analysis_call_and_deterministic_selection() -> None:
    analysis = CountingAnalysisAgent()
    result = build_orchestrator(analysis_agent=analysis).run(build_demo_request())
    assert result.status == "completed"
    assert analysis.calls == 1
    assert len(analysis.request.route_outcomes) == 3
    assert result.selection.selected_strategy_id.endswith("hybrid_r1")
    assert result.selected_types == ("hybrid",)
    assert tuple(candidate.state for candidate in result.candidates) == (
        "backtested_not_selected",
        "backtested_not_selected",
        "selected",
    )
    assert result.post_backtest_analysis.recommended_strategy_ids != (
        result.selection.selected_strategy_id,
    )


def test_resumer_re_reviews_only_exact_completion_marker_false_positive() -> None:
    original = build_orchestrator().run(build_demo_request())
    candidate = original.candidates[0]
    assert candidate.generated_code is not None
    marker = candidate.generated_code.compiler_metadata["completion_marker"]
    finding = CodeRiskFinding(
        code="MISSING_COMPLETION_SIGNAL",
        severity="blocking",
        category="execution",
        code_location="on_alpha_end",
        evidence=f'self.debug("{marker}")',
        risk="incorrect Prompt interpretation",
        required_correction="use the registered completion contract",
    )
    rejected = candidate.model_copy(
        update={
            "state": "rejected_by_code_risk",
            "code_risk_review": candidate.code_risk_review.model_copy(
                update={"verdict": "changes_required", "findings": (finding,)}
            ),
            "smoke_test": None,
            "backtest_result": None,
            "failure_reasons": ("MISSING_COMPLETION_SIGNAL",),
        }
    )
    partial = original.model_copy(
        update={"candidates": (rejected, *original.candidates[1:])}
    )
    backtest = RecordingBacktestProvider()
    resumed = OptimizationResumer(
        backtest_provider=backtest,
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    ).resume_supported_failures(
        partial,
        constraints=build_demo_request().constraints,
        code_risk_agent=MockCodeRiskAgent(),
    )

    retried = resumed.candidates[0]
    assert retried.code_risk_review.verdict == "approve"
    assert retried.backtest_result is not None
    assert retried.state in {"backtested_not_selected", "selected"}
    assert backtest.smoke_calls == 1
    assert backtest.run_calls == 1

    repeated = OptimizationResumer(
        backtest_provider=RecordingBacktestProvider(),
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    ).resume_supported_failures(
        resumed,
        constraints=build_demo_request().constraints,
        code_risk_agent=MockCodeRiskAgent(),
    )
    assert repeated.selection.selected_strategy_id == resumed.selection.selected_strategy_id


class BarrierDesigner(MockStrategyDesigner):
    def __init__(self) -> None:
        self.barrier = threading.Barrier(3)

    def design(self, request):
        self.barrier.wait(timeout=2)
        return super().design(request)


def test_three_route_pipelines_are_dispatched_concurrently() -> None:
    orchestrator = OptimisationOrchestrator(
        designer=BarrierDesigner(),
        code_risk_agent=MockCodeRiskAgent(),
        backtest_provider=MockBacktestProvider(),
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    result = orchestrator.run(build_demo_request())
    assert result.status == "completed"
    assert [event.sequence for event in result.audit_log] == list(
        range(1, len(result.audit_log) + 1)
    )


class ReferenceCopyingDesigner(MockStrategyDesigner):
    def design(self, request):
        references = {
            item.strategy_role: item.strategy_spec
            for item in request.evidence_summary.reference_strategies
        }
        if request.candidate_type == "traditional":
            logic = references["baseline_b1"].logic
            changes = ExecutionChanges()
        elif request.candidate_type == "ml":
            logic = references["baseline_b3"].logic
            changes = ExecutionChanges()
        else:
            return super().design(request)
        return CandidateDesign(
            candidate_type=request.candidate_type,
            logic=logic,
            execution_changes=changes,
            risk_changes=RiskChanges(),
            design_reasons=("copy reference to exercise deterministic deduplication",),
            expected_tradeoffs=("duplicate must not consume a backtest",),
        )


def test_reference_semantic_duplicates_are_not_compiled_or_backtested() -> None:
    backtest = RecordingBacktestProvider()
    orchestrator = OptimisationOrchestrator(
        designer=ReferenceCopyingDesigner(),
        code_risk_agent=MockCodeRiskAgent(),
        backtest_provider=backtest,
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    result = orchestrator.run(build_demo_request())
    duplicates = [c for c in result.candidates if c.state == "duplicate_of_reference"]
    assert {c.duplicate_of_strategy_id for c in duplicates} == {
        "baseline_b1_momentum_v1",
        "baseline_b3_gbdt_v1",
    }
    assert backtest.run_calls == 1


class RecordingRoundDesigner(MockStrategyDesigner):
    def __init__(self):
        self.requests = []

    def design(self, request):
        self.requests.append(request)
        return super().design(request)


class NoImprovementBacktest(RecordingBacktestProvider):
    def run(self, spec, code):
        result = super().run(spec, code)
        return result.model_copy(
            update={
                "metrics": BacktestMetrics(
                    cagr=0.05,
                    sharpe_ratio=0.5,
                    sortino_ratio=0.6,
                    max_drawdown=0.2,
                    annual_volatility=0.15,
                    turnover=0.8,
                    total_fees=120.0,
                )
            }
        )


def test_second_round_receives_same_route_prior_attempt_and_remains_unique() -> None:
    designer = RecordingRoundDesigner()
    backtest = NoImprovementBacktest()
    orchestrator = OptimisationOrchestrator(
        designer=designer,
        code_risk_agent=MockCodeRiskAgent(),
        backtest_provider=backtest,
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    request = build_demo_request()
    request = request.model_copy(
        update={"constraints": request.constraints.model_copy(update={"max_rounds": 2})}
    )
    result = orchestrator.run(request)
    assert len(result.candidates) == 6
    assert backtest.run_calls == 6
    round_two = [request for request in designer.requests if request.round_number == 2]
    assert len(round_two) == 3
    assert all(len(request.prior_attempts) == 1 for request in round_two)


def test_completed_result_can_continue_only_from_the_next_round() -> None:
    designer = RecordingRoundDesigner()
    backtest = NoImprovementBacktest()
    orchestrator = OptimisationOrchestrator(
        designer=designer,
        code_risk_agent=MockCodeRiskAgent(),
        backtest_provider=backtest,
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    request = build_demo_request()
    first_two = request.model_copy(
        update={"constraints": request.constraints.model_copy(update={"max_rounds": 2})}
    )
    partial = orchestrator.run(first_two)
    continued = orchestrator.run(request, initial_result=partial)
    assert len(partial.candidates) == 6
    assert len(continued.candidates) == 9
    assert [candidate.round_number for candidate in continued.candidates[-3:]] == [3, 3, 3]
    round_three = [item for item in designer.requests if item.round_number == 3]
    assert len(round_three) == 3
    assert all(len(item.prior_attempts) == 2 for item in round_three)


class InvalidAnalysisAgent(MockPostBacktestAnalysisAgent):
    def analyze(self, request):
        analysis = super().analyze(request)
        first = analysis.metric_analysis[0]
        invalid_value = first.values[0].model_copy(update={"value": first.values[0].value + 1})
        invalid_first = first.model_copy(update={"values": (invalid_value, *first.values[1:])})
        return analysis.model_copy(
            update={"metric_analysis": (invalid_first, *analysis.metric_analysis[1:])}
        )


def test_invalid_post_backtest_analysis_is_not_retained_as_completed() -> None:
    result = build_orchestrator(analysis_agent=InvalidAnalysisAgent()).run(build_demo_request())
    assert result.status == "failed"
    assert result.post_backtest_analysis is None
    assert "METRIC_VALUES_MISMATCH" in result.analysis_error


def test_analysis_validation_tolerates_json_float_rounding() -> None:
    analysis = CountingAnalysisAgent()
    completed = build_orchestrator(analysis_agent=analysis).run(build_demo_request())
    first_metric = completed.post_backtest_analysis.metric_analysis[0]
    first_value = first_metric.values[0]
    rounded = first_value.model_copy(update={"value": first_value.value + 1e-12})
    adjusted_metric = first_metric.model_copy(update={"values": (rounded, *first_metric.values[1:])})
    adjusted = completed.post_backtest_analysis.model_copy(
        update={"metric_analysis": (adjusted_metric, *completed.post_backtest_analysis.metric_analysis[1:])}
    )
    assert validate_post_backtest_analysis(analysis.request, adjusted) == ()


def test_code_risk_runs_after_deterministic_compilation_and_before_backtest() -> None:
    events = []
    risk = RecordingRiskAgent(events)
    result = build_orchestrator(
        compiler=RecordingCompiler(events),
        risk_agent=risk,
        backtest=RecordingBacktestProvider(events),
    ).run(build_demo_request())
    assert result.status == "completed"
    for route in ("traditional", "ml", "hybrid"):
        route_events = [stage for event_route, stage in events if event_route == route]
        assert route_events == ["strategy_compilation", "code_risk", "smoke_test", "backtest"]
    assert len(risk.requests) == 3


class BlockingRiskAgent(MockCodeRiskAgent):
    def review(self, request):
        return CodeRiskReview(
            strategy_id=request.strategy_spec.strategy_id,
            reviewed_source_sha256=request.generated_code.source_sha256,
            spec_sha256=request.generated_code.spec_sha256,
            verdict="changes_required",
            findings=(
                CodeRiskFinding(
                    code="UNRESOLVED_EXPOSURE_PATH",
                    severity="blocking",
                    category="exposure",
                    code_location="main.py:Rebalance",
                    evidence="an exposure path remains open",
                    risk="the implementation can retain an unintended position",
                    required_correction="correct the deterministic compiler or template offline",
                ),
            ),
        )


def test_blocking_code_risk_stops_without_model_repair_or_backtest() -> None:
    backtest = RecordingBacktestProvider()
    result = build_orchestrator(
        risk_agent=BlockingRiskAgent(), backtest=backtest
    ).run(build_demo_request())
    assert backtest.smoke_calls == 0
    assert backtest.run_calls == 0
    assert all(candidate.state == "rejected_by_code_risk" for candidate in result.candidates)
    assert all("correct the deterministic compiler" in candidate.failure_reasons[0] for candidate in result.candidates)


class BrokenCompiler(DeterministicStrategyCompiler):
    def compile(self, request):
        valid = super().compile(request)
        source = "def broken("
        return valid.model_copy(
            update={
                "source": source,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
        )


def test_static_validation_failure_stops_before_risk_and_backtest() -> None:
    events = []
    backtest = RecordingBacktestProvider(events)
    risk = RecordingRiskAgent(events)
    result = build_orchestrator(
        compiler=BrokenCompiler(), risk_agent=risk, backtest=backtest
    ).run(build_demo_request())
    assert not risk.requests
    assert backtest.smoke_calls == 0
    assert backtest.run_calls == 0
    assert all(candidate.state == "rejected_by_code_validation" for candidate in result.candidates)


class SmokeFailsForTraditional(MockBacktestProvider):
    def __init__(self):
        self.smoke_calls = 0
        self.run_calls = 0

    def smoke_test(self, spec, code):
        self.smoke_calls += 1
        if spec.candidate_type == "traditional":
            return SmokeTestResult(
                strategy_id=spec.strategy_id,
                status="failed",
                diagnostics=("compile error",),
                provider="mock_lean_smoke",
            )
        return super().smoke_test(spec, code)

    def run(self, spec, code):
        self.run_calls += 1
        return super().run(spec, code)


def test_smoke_failure_terminates_route_without_retry() -> None:
    provider = SmokeFailsForTraditional()
    result = build_orchestrator(backtest=provider).run(build_demo_request())
    traditional = next(c for c in result.candidates if c.candidate_type == "traditional")
    assert traditional.state == "rejected_by_smoke_test"
    assert traditional.backtest_result is None
    assert provider.smoke_calls == 3
    assert provider.run_calls == 2


class FullBacktestFails(MockBacktestProvider):
    def run(self, spec, code):
        return BacktestResult(
            run_id=f"failed-{spec.strategy_id}",
            strategy_id=spec.strategy_id,
            strategy_role="candidate",
            status="failed",
            dataset_split="validation",
            provider="mock_lean",
            metrics=None,
            warnings=("LEAN_RUNTIME_FAILURE",),
        )


def test_failed_full_backtest_is_not_marked_as_completed_candidate() -> None:
    result = build_orchestrator(backtest=FullBacktestFails()).run(build_demo_request())
    assert all(candidate.state == "rejected_by_backtest" for candidate in result.candidates)
    assert all(candidate.backtest_result is not None for candidate in result.candidates)
    assert all(candidate.failure_reasons == ("LEAN_RUNTIME_FAILURE",) for candidate in result.candidates)
    assert result.selection.selected_strategy_id is None


def test_test_set_evidence_is_rejected_before_design() -> None:
    with pytest.raises(ValueError, match="test-set evidence is forbidden"):
        build_orchestrator().run(build_demo_request(include_test_evidence=True))


class WrongDigestRiskAgent(MockCodeRiskAgent):
    def review(self, request):
        review = super().review(request)
        return review.model_copy(update={"reviewed_source_sha256": "wrong-source"})


def test_code_risk_review_must_bind_to_current_source_digest() -> None:
    backtest = RecordingBacktestProvider()
    result = build_orchestrator(
        risk_agent=WrongDigestRiskAgent(), backtest=backtest
    ).run(build_demo_request())
    assert backtest.smoke_calls == 0
    assert backtest.run_calls == 0
    assert all(candidate.state == "rejected_by_code_risk" for candidate in result.candidates)
    assert all(
        "RISK_REVIEW_SOURCE_DIGEST_MISMATCH" in candidate.failure_reasons
        for candidate in result.candidates
    )


def test_selector_never_selects_a_rejected_candidate_with_attached_result() -> None:
    request = build_demo_request()
    completed = build_orchestrator().run(request)
    rejected = tuple(
        candidate.model_copy(update={"state": "rejected_by_code_risk"})
        for candidate in completed.candidates
    )
    selection = CandidateSelector().select(
        evidence=request.evidence,
        candidates=rejected,
        constraints=request.constraints,
    )
    assert selection.selected_strategy_id is None
    assert all(not candidate.eligible for candidate in selection.candidates)
