from __future__ import annotations

import json
from types import SimpleNamespace

import ablation.provider as provider_module
from agent.prompts import TRACK_SPEC_EXAMPLES


def _run_settings() -> dict:
    return {
        "symbols": ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
        "start_date": "2020-01-02",
        "end_date": "2024-12-31",
        "benchmark": "SPY",
        "transaction_cost_bps": 10,
        "slippage_bps": 5,
    }


def _client() -> SimpleNamespace:
    completions = SimpleNamespace(create=lambda **_: None)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_provider_options_reads_environment_without_exposing_extra_values(monkeypatch):
    monkeypatch.setenv("API_KEY", "  secret  ")
    monkeypatch.setenv("BASE_URL", "https://provider.invalid/")
    monkeypatch.setenv("MODEL", "  model-v1  ")
    monkeypatch.setenv("THINKING_ENABLED", "yes")

    assert provider_module.provider_options() == {
        "api_key": "secret",
        "base_url": "https://provider.invalid",
        "model": "model-v1",
        "thinking_enabled": True,
    }
    assert provider_module.provider_options(thinking_enabled=False)[
        "thinking_enabled"
    ] is False


def test_no_example_designer_removes_only_the_nested_example():
    designer = provider_module.NoExampleDesigner(
        api_key="test",
        base_url="https://provider.invalid",
        model="test-model",
        thinking_enabled=False,
        client=_client(),
    )

    messages = designer.messages(
        track="Traditional",
        run_settings=_run_settings(),
        baseline_results=[],
    )
    request = json.loads(messages[1]["content"])

    assert "valid_strategy_spec_example" not in request
    assert request["assigned_track"] == "Traditional"
    assert request["parameter_rules"]
    assert request["output_shape"]


def test_designer_for_arm_selects_variant_and_thinking_mode(monkeypatch):
    created: list[tuple[str, dict]] = []

    class DefaultDesigner:
        def __init__(self, **options):
            created.append(("default", options))

    class ExampleFreeDesigner:
        def __init__(self, **options):
            created.append(("no_example", options))

    def fake_options(*, thinking_enabled=None):
        return {"thinking_enabled": thinking_enabled, "marker": "options"}

    monkeypatch.setattr(provider_module, "DeepSeekDesigner", DefaultDesigner)
    monkeypatch.setattr(provider_module, "NoExampleDesigner", ExampleFreeDesigner)
    monkeypatch.setattr(provider_module, "provider_options", fake_options)

    provider_module.designer_for_arm("full")
    provider_module.designer_for_arm("no_thinking")
    provider_module.designer_for_arm("no_example")

    assert created == [
        ("default", {"thinking_enabled": None, "marker": "options"}),
        ("default", {"thinking_enabled": False, "marker": "options"}),
        ("no_example", {"thinking_enabled": None, "marker": "options"}),
    ]


def test_generate_once_uses_one_transport_attempt_and_one_validation():
    calls: dict[str, object] = {}
    payload = {
        "design": {"reference_baselines": ["Momentum Rank"]},
        "strategy_spec": TRACK_SPEC_EXAMPLES["Traditional"],
    }

    class CompletionClient:
        def complete_json(self, messages, **kwargs):
            calls["messages"] = messages
            calls["completion_kwargs"] = kwargs
            return {
                "payload": payload,
                "usage": {"total_tokens": 12},
                "trace": {"attempts": [{"attempt": 1}]},
            }

    class Designer:
        deepseek = CompletionClient()

        def messages(self, **kwargs):
            calls["message_kwargs"] = kwargs
            return [{"role": "system", "content": "fixed"}]

        def _validated_proposal(self, value, track, **kwargs):
            calls["validation"] = (value, track, kwargs)
            return {"design": {"ok": True}, "strategy_spec": value["strategy_spec"]}

    result = provider_module.generate_once(
        Designer(),
        track="Traditional",
        run_settings=_run_settings(),
        baseline_results=[],
    )

    assert calls["completion_kwargs"]["max_attempts"] == 1
    assert calls["validation"][1] == "Traditional"
    assert calls["validation"][2]["symbol_count"] == 5
    assert result["generation_retries"] == 0
    assert result["usage"] == {"total_tokens": 12}


def test_generate_proposal_routes_no_retry_without_calling_generate(monkeypatch):
    calls: list[tuple[str, object]] = []

    class Designer:
        def generate(self, **kwargs):
            calls.append(("generate", kwargs))
            return {"route": "generate"}

    designer = Designer()
    monkeypatch.setattr(provider_module, "designer_for_arm", lambda arm: designer)
    monkeypatch.setattr(
        provider_module,
        "generate_once",
        lambda selected, **kwargs: calls.append(("once", selected))
        or {"route": "once"},
    )

    common = {
        "track": "Traditional",
        "run_settings": _run_settings(),
        "baseline_results": [],
    }
    assert provider_module.generate_proposal(arm="no_retry", **common) == {
        "route": "once"
    }
    assert provider_module.generate_proposal(arm="full", **common) == {
        "route": "generate"
    }
    assert calls[0] == ("once", designer)
    assert calls[1][0] == "generate"
