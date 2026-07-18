from __future__ import annotations

import pytest

from alphaforge.agents.providers.structured import StructuredModelClient, StructuredOutputError
from alphaforge.config import ModelSettings
from alphaforge.schemas.agent_outputs import CandidateDesign


class StubStructuredClient(StructuredModelClient):
    def __init__(self, responses):
        super().__init__(ModelSettings(api_key="test", model="test", base_url="https://example.invalid"))
        self.responses = iter(responses)
        self.calls = 0

    def _request(self, **kwargs):
        self.calls += 1
        return next(self.responses)


def test_structured_client_retries_once_with_validation_feedback() -> None:
    client = StubStructuredClient(
        [
            '{"candidate_type":"traditional"}',
            """{
              "candidate_type": "traditional",
              "logic": {"kind": "traditional", "signal": "momentum_rank", "lookback_days": 126},
              "execution_changes": {"top_k": 3},
              "risk_changes": {},
              "design_reasons": ["bounded design"],
              "expected_tradeoffs": ["turnover may increase"]
            }""",
        ]
    )
    result = client.complete(
        output_model=CandidateDesign,
        system_prompt="test",
        payload={"test": True},
    )
    assert client.calls == 2
    assert result.logic.kind == "traditional"


def test_structured_client_rejects_after_one_correction_attempt() -> None:
    client = StubStructuredClient(["{}", "{}"])
    with pytest.raises(StructuredOutputError, match="after one correction attempt"):
        client.complete(
            output_model=CandidateDesign,
            system_prompt="test",
            payload={"test": True},
        )
    assert client.calls == 2
