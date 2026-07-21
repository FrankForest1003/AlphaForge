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
from alphaforge.schemas.backtest import SmokeTestResult
from alphaforge.services.analysis_validator import validate_post_backtest_analysis
from alphaforge.services.candidate_selector import CandidateSelector


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
