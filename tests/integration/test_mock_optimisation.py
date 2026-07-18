from __future__ import annotations

import ast
import hashlib

import pytest

from alphaforge.agents.orchestrator import OptimisationOrchestrator
from alphaforge.agents.providers.mock import MockAgentProvider, MockBacktestProvider
from alphaforge.codegen.generator import DeterministicCodeGenerator, DeterministicRepairProvider
from alphaforge.demo import build_demo_request


@pytest.fixture
def orchestrator() -> OptimisationOrchestrator:
    return OptimisationOrchestrator(
        agent_provider=MockAgentProvider(),
        code_generator=DeterministicCodeGenerator(),
        backtest_provider=MockBacktestProvider(),
    )


def test_mock_closed_loop_produces_three_distinct_routes(
    orchestrator: OptimisationOrchestrator,
) -> None:
    result = orchestrator.run(build_demo_request())
    assert result.status == "completed"
    assert tuple(candidate.candidate_type for candidate in result.candidates) == (
        "traditional",
        "ml",
        "hybrid",
    )
    assert result.accepted_types == ("traditional", "hybrid")
    assert result.candidates[1].state == "rejected_after_backtest"
    assert "DRAWDOWN_DETERIORATION" in result.candidates[1].decision.reason_codes

    for candidate in result.candidates:
        assert candidate.proposal.spec.logic.kind == candidate.candidate_type
        assert candidate.generated_code is not None
        ast.parse(candidate.generated_code.source)
        assert candidate.backtest_result.dataset_split == "validation"

    assert [event.sequence for event in result.audit_log] == list(
        range(1, len(result.audit_log) + 1)
    )


def test_optimisation_refuses_test_set_evidence(
    orchestrator: OptimisationOrchestrator,
) -> None:
    with pytest.raises(ValueError, match="test-set evidence is forbidden"):
        orchestrator.run(build_demo_request(include_test_evidence=True))


class BrokenCodeGenerator:
    def generate(self, spec):
        code = DeterministicCodeGenerator().generate(spec)
        broken_source = "def broken("
        return code.model_copy(
            update={
                "source": broken_source,
                "sha256": hashlib.sha256(broken_source.encode()).hexdigest(),
            }
        )


def test_repair_regenerates_code_without_changing_spec_semantics() -> None:
    orchestrator = OptimisationOrchestrator(
        agent_provider=MockAgentProvider(),
        code_generator=BrokenCodeGenerator(),
        repair_provider=DeterministicRepairProvider(),
        backtest_provider=MockBacktestProvider(),
    )
    result = orchestrator.run(build_demo_request())
    repair_events = [event for event in result.audit_log if event.stage == "code_repair"]
    assert len(repair_events) == 3
    assert all(event.outcome == "completed" for event in repair_events)
    assert all(candidate.code_validation.valid for candidate in result.candidates)
    assert all(
        candidate.generated_code.spec_sha256
        == DeterministicCodeGenerator().generate(candidate.proposal.spec).spec_sha256
        for candidate in result.candidates
    )
