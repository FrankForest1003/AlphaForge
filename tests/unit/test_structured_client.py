from __future__ import annotations

import json
import inspect
from types import SimpleNamespace

import pytest

from alphaforge.agents.providers.structured import (
    CompletionPolicy,
    EmptyModelOutputError,
    StructuredModelClient,
    StructuredOutputError,
)
from alphaforge.config import ModelSettings
from alphaforge.agents.context import ContextAssembler
from alphaforge.schemas.agent_outputs import CandidateDesign
from alphaforge.agents.providers.llm import (
    ANALYSIS_POLICY,
    DESIGN_POLICY,
    RISK_POLICY,
)


class StubStructuredClient(StructuredModelClient):
    def __init__(self, responses):
        super().__init__(ModelSettings(api_key="test", model="test", base_url="https://example.invalid"))
        self.responses = iter(responses)
        self.calls = 0

    def _request(self, **kwargs):
        self.calls += 1
        return next(self.responses)


def _test_bundle():
    return ContextAssembler().build(
        agent_role="strategy_designer", candidate_type="traditional"
    )


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
        payload={"test": True},
        context_bundle=_test_bundle(),
    )
    assert client.calls == 2
    assert result.logic.kind == "traditional"


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )


def test_request_uses_openai_sdk_without_putting_api_key_in_messages() -> None:
    completions = FakeCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = ModelSettings(
        api_key="secret-not-for-messages",
        model="compatible-model",
        base_url="https://example.invalid",
    )
    client = StructuredModelClient(settings, client=sdk)  # type: ignore[arg-type]

    content = client._request(
        payload={"strategy_id": "candidate_1"},
        schema={"type": "object"},
        context_bundle=_test_bundle(),
    )

    assert content == '{"ok": true}'
    assert completions.kwargs["model"] == "compatible-model"
    assert completions.kwargs["response_format"] == {"type": "json_object"}
    assert completions.kwargs["reasoning_effort"] == "high"
    assert completions.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "temperature" not in completions.kwargs
    user_message = json.loads(completions.kwargs["messages"][1]["content"])
    assert user_message == {
        "json_schema": {"type": "object"},
        "input": {"strategy_id": "candidate_1"},
    }
    assert "secret-not-for-messages" not in str(completions.kwargs["messages"])
    assert completions.kwargs["messages"][0]["content"] == _test_bundle().render()


def test_complete_exposes_no_free_text_system_prompt_parameter() -> None:
    parameters = inspect.signature(StructuredModelClient.complete).parameters
    assert "system_prompt" not in parameters
    assert "context_bundle" in parameters


def test_retry_preserves_exact_prompt_and_trace_identity() -> None:
    class RecordingCompletions:
        def __init__(self) -> None:
            self.calls = []
            self.responses = iter(
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

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=next(self.responses)),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

    completions = RecordingCompletions()
    traces = []
    client = StructuredModelClient(
        ModelSettings(api_key="secret", model="model", base_url="https://example.invalid"),
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),  # type: ignore[arg-type]
        trace_sink=traces.append,
    )
    bundle = _test_bundle()
    result = client.complete(
        output_model=CandidateDesign,
        payload={"candidate_type": "traditional"},
        context_bundle=bundle,
    )

    assert result.logic.kind == "traditional"
    assert len(completions.calls) == 2
    assert [call["messages"][0]["content"] for call in completions.calls] == [
        bundle.render(),
        bundle.render(),
    ]
    retry_input = json.loads(completions.calls[1]["messages"][1]["content"])["input"]
    assert "validation_feedback" in retry_input
    requests = [event for event in traces if event["kind"] == "llm_request"]
    assert requests[0]["context_bundle"]["prompt_id"] == bundle.prompt_id
    assert requests[0]["context_bundle"]["prompt_version"] == "2.0"
    assert requests[0]["context_bundle"]["prompt_sha256"] == bundle.bundle_sha256
    assert requests[0]["context_bundle"]["character_count"] == bundle.character_count
    assert requests[0]["system_prompt"] == bundle.render()


def test_request_applies_critical_reasoning_policy() -> None:
    completions = FakeCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = StructuredModelClient(
        ModelSettings(api_key="test", model="advanced-model", base_url="https://example.invalid"),
        client=sdk,  # type: ignore[arg-type]
    )
    client._request(
        payload={},
        schema={"type": "object"},
        context_bundle=_test_bundle(),
        policy=CompletionPolicy("max", 16000),
    )
    assert completions.kwargs["reasoning_effort"] == "max"
    assert completions.kwargs["max_tokens"] == 16000
    assert "temperature" not in completions.kwargs


def test_runtime_agent_policies_use_high_reasoning_after_latency_tuning() -> None:
    assert {
        DESIGN_POLICY.reasoning_effort,
        RISK_POLICY.reasoning_effort,
        ANALYSIS_POLICY.reasoning_effort,
    } == {"high"}


def test_structured_client_rejects_after_one_correction_attempt() -> None:
    client = StubStructuredClient(["{}", "{}"])
    with pytest.raises(StructuredOutputError, match="after one correction attempt"):
        client.complete(
            output_model=CandidateDesign,
            payload={"test": True},
            context_bundle=_test_bundle(),
        )
    assert client.calls == 2


def test_empty_final_content_gets_one_correction_attempt() -> None:
    class EmptyThenValidClient(StubStructuredClient):
        def _request(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise EmptyModelOutputError("empty final content")
            return next(self.responses)

    client = EmptyThenValidClient(
        [
            """{
              "candidate_type": "traditional",
              "logic": {"kind": "traditional", "signal": "momentum_rank", "lookback_days": 126},
              "execution_changes": {"top_k": 3},
              "risk_changes": {},
              "design_reasons": ["bounded design"],
              "expected_tradeoffs": ["turnover may increase"]
            }"""
        ]
    )
    result = client.complete(
        output_model=CandidateDesign,
        payload={},
        context_bundle=_test_bundle(),
    )
    assert result.candidate_type == "traditional"
    assert client.calls == 2


def test_post_schema_validator_participates_in_same_retry_budget() -> None:
    client = StubStructuredClient(
        [
            """{
              "candidate_type": "traditional",
              "logic": {"kind": "traditional", "signal": "momentum_rank", "lookback_days": 126},
              "execution_changes": {"top_k": 3},
              "risk_changes": {},
              "design_reasons": ["first"],
              "expected_tradeoffs": ["first"]
            }""",
            """{
              "candidate_type": "traditional",
              "logic": {"kind": "traditional", "signal": "momentum_rank", "lookback_days": 126},
              "execution_changes": {"top_k": 3},
              "risk_changes": {},
              "design_reasons": ["corrected"],
              "expected_tradeoffs": ["corrected"]
            }""",
        ]
    )
    validations = 0

    def validate(result):
        nonlocal validations
        validations += 1
        if validations == 1:
            raise ValueError("template boundary failed")

    result = client.complete(
        output_model=CandidateDesign,
        payload={},
        context_bundle=_test_bundle(),
        result_validator=validate,
    )
    assert result.design_reasons == ("corrected",)
    assert client.calls == 2
