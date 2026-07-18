from __future__ import annotations

import hashlib

import pytest

from alphaforge.agents.orchestrator import OptimisationOrchestrator
from alphaforge.agents.providers.mock import (
    MockBacktestProvider,
    MockCodeRiskAgent,
    MockPostBacktestAnalysisAgent,
    MockQCCodeAgent,
    MockRepairAgent,
    MockStrategyDesigner,
)
from alphaforge.demo import build_demo_environment, build_demo_request
from alphaforge.services.candidate_selector import CandidateSelector
from alphaforge.schemas.agent_outputs import (
    CodeRiskFinding,
    CodeRiskReview,
    GeneratedCode,
)


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


class RecordingCodeAgent(MockQCCodeAgent):
    def __init__(self, events):
        self.events = events

    def generate(self, request):
        self.events.append("code_generation")
        return super().generate(request)


class RecordingRiskAgent(MockCodeRiskAgent):
    def __init__(self, events):
        self.events = events
        self.requests = []

    def review(self, request):
        self.events.append("code_risk")
        self.requests.append(request)
        assert "backtest_result" not in type(request).model_fields
        return super().review(request)


class RecordingBacktestProvider(MockBacktestProvider):
    def __init__(self, events):
        self.events = events

    def smoke_test(self, spec, code):
        self.events.append("smoke_test")
        return super().smoke_test(spec, code)

    def run(self, spec, code):
        self.events.append("backtest")
        return super().run(spec, code)


def build_orchestrator(*, analysis_agent=None, code_agent=None, risk_agent=None, backtest=None):
    return OptimisationOrchestrator(
        designer=MockStrategyDesigner(),
        qc_code_agent=code_agent or MockQCCodeAgent(),
        code_risk_agent=risk_agent or MockCodeRiskAgent(),
        repair_agent=MockRepairAgent(),
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


def test_code_risk_runs_after_generation_and_before_any_backtest() -> None:
    events = []
    risk = RecordingRiskAgent(events)
    result = build_orchestrator(
        code_agent=RecordingCodeAgent(events),
        risk_agent=risk,
        backtest=RecordingBacktestProvider(events),
    ).run(build_demo_request())
    assert result.status == "completed"
    for offset in (0, 4, 8):
        assert events[offset : offset + 4] == [
            "code_generation",
            "code_risk",
            "smoke_test",
            "backtest",
        ]
    assert len(risk.requests) == 3


class RiskRepairOnceAgent(MockCodeRiskAgent):
    def __init__(self) -> None:
        self.calls = 0

    def review(self, request):
        self.calls += 1
        if self.calls == 1:
            return CodeRiskReview(
                strategy_id=request.strategy_spec.strategy_id,
                reviewed_source_sha256=request.generated_code.source_sha256,
                spec_sha256=request.generated_code.spec_sha256,
                verdict="repair_required",
                findings=(
                    CodeRiskFinding(
                        code="DUPLICATE_ORDER_PATH",
                        severity="blocking",
                        category="order_lifecycle",
                        code_location="main.py:Initialize",
                        evidence="duplicate schedule registration",
                        risk="orders may be submitted twice",
                        repair_instruction="register the schedule once",
                    ),
                ),
            )
        return super().review(request)


class CountingRepairAgent(MockRepairAgent):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.spec_digests = []

    def repair(self, request):
        self.calls += 1
        self.spec_digests.append(request.failed_code.spec_sha256)
        return super().repair(request)


def test_blocking_code_risk_triggers_repair_and_re_review() -> None:
    risk = RiskRepairOnceAgent()
    repair = CountingRepairAgent()
    orchestrator = OptimisationOrchestrator(
        designer=MockStrategyDesigner(),
        qc_code_agent=MockQCCodeAgent(),
        code_risk_agent=risk,
        repair_agent=repair,
        backtest_provider=MockBacktestProvider(),
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    result = orchestrator.run(build_demo_request())
    assert repair.calls == 1
    assert risk.calls == 4
    assert all(candidate.backtest_result is not None for candidate in result.candidates)
    assert repair.spec_digests[0] == result.candidates[0].generated_code.spec_sha256


class BrokenQCCodeAgent(MockQCCodeAgent):
    def generate(self, request):
        valid = super().generate(request)
        source = "def broken("
        return valid.model_copy(
            update={
                "source": source,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
        )


def test_static_validation_failure_repairs_before_risk_and_backtest() -> None:
    repair = CountingRepairAgent()
    orchestrator = OptimisationOrchestrator(
        designer=MockStrategyDesigner(),
        qc_code_agent=BrokenQCCodeAgent(),
        code_risk_agent=MockCodeRiskAgent(),
        repair_agent=repair,
        backtest_provider=MockBacktestProvider(),
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    result = orchestrator.run(build_demo_request())
    assert repair.calls == 3
    assert all(candidate.code_validation.valid for candidate in result.candidates)
    assert all(candidate.backtest_result is not None for candidate in result.candidates)


class SmokeFailsOnceProvider(MockBacktestProvider):
    def __init__(self):
        self.smoke_calls = 0

    def smoke_test(self, spec, code):
        self.smoke_calls += 1
        if self.smoke_calls == 1:
            from alphaforge.schemas.backtest import SmokeTestResult

            return SmokeTestResult(
                strategy_id=spec.strategy_id,
                status="failed",
                diagnostics=("compile error",),
                provider="mock_lean_smoke",
            )
        return super().smoke_test(spec, code)


def test_smoke_failure_repairs_then_repeats_static_and_risk_checks() -> None:
    repair = CountingRepairAgent()
    provider = SmokeFailsOnceProvider()
    orchestrator = OptimisationOrchestrator(
        designer=MockStrategyDesigner(),
        qc_code_agent=MockQCCodeAgent(),
        code_risk_agent=MockCodeRiskAgent(),
        repair_agent=repair,
        backtest_provider=provider,
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    result = orchestrator.run(build_demo_request())
    assert repair.calls == 1
    assert provider.smoke_calls == 4
    assert all(candidate.backtest_result is not None for candidate in result.candidates)


def test_test_set_evidence_is_rejected_before_design() -> None:
    with pytest.raises(ValueError, match="test-set evidence is forbidden"):
        build_orchestrator().run(build_demo_request(include_test_evidence=True))


class AlwaysRepairRiskAgent(MockCodeRiskAgent):
    def review(self, request):
        return CodeRiskReview(
            strategy_id=request.strategy_spec.strategy_id,
            reviewed_source_sha256=request.generated_code.source_sha256,
            spec_sha256=request.generated_code.spec_sha256,
            verdict="repair_required",
            findings=(
                CodeRiskFinding(
                    code="UNRESOLVED_EXPOSURE_PATH",
                    severity="blocking",
                    category="exposure",
                    code_location="main.py:1",
                    evidence="the simulated defect remains after repair",
                    risk="the implementation can leave an unintended position",
                    repair_instruction="close the unresolved exposure path",
                ),
            ),
        )


class CountingBacktestProvider(MockBacktestProvider):
    def __init__(self) -> None:
        self.smoke_calls = 0
        self.run_calls = 0

    def smoke_test(self, spec, code):
        self.smoke_calls += 1
        return super().smoke_test(spec, code)

    def run(self, spec, code):
        self.run_calls += 1
        return super().run(spec, code)


def test_repair_limit_blocks_smoke_and_full_backtest() -> None:
    repair = CountingRepairAgent()
    backtest = CountingBacktestProvider()
    orchestrator = OptimisationOrchestrator(
        designer=MockStrategyDesigner(),
        qc_code_agent=MockQCCodeAgent(),
        code_risk_agent=AlwaysRepairRiskAgent(),
        repair_agent=repair,
        backtest_provider=backtest,
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    result = orchestrator.run(build_demo_request())
    assert repair.calls == 6
    assert backtest.smoke_calls == 0
    assert backtest.run_calls == 0
    assert all(candidate.state == "rejected_by_code_risk" for candidate in result.candidates)
    assert result.selection.selected_strategy_id is None
    assert result.selection.no_robust_improvement


class WrongDigestRiskAgent(MockCodeRiskAgent):
    def review(self, request):
        review = super().review(request)
        return review.model_copy(update={"reviewed_source_sha256": "wrong-source"})


def test_code_risk_review_must_bind_to_current_source_digest() -> None:
    backtest = CountingBacktestProvider()
    result = build_orchestrator(
        risk_agent=WrongDigestRiskAgent(),
        backtest=backtest,
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
    assert all(candidate.checks[0].name == "pipeline_eligible" for candidate in selection.candidates)
