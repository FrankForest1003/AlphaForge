from __future__ import annotations

import copy
import json
import os
from typing import Any

from agent.critic import DeepSeekCritic
from agent.designer import DeepSeekDesigner


def provider_options(*, thinking_enabled: bool | None = None) -> dict[str, Any]:
    """Build the existing OpenAI-compatible provider options without persisting secrets."""

    if thinking_enabled is None:
        thinking_enabled = os.getenv("THINKING_ENABLED", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    return {
        "api_key": os.getenv("API_KEY", "").strip(),
        "base_url": os.getenv("BASE_URL", "https://api.deepseek.com").rstrip("/"),
        "model": os.getenv("MODEL", "deepseek-v4-pro").strip(),
        "thinking_enabled": thinking_enabled,
    }


class NoExampleDesigner(DeepSeekDesigner):
    """Designer arm that removes only the valid nested strategy example."""

    def messages(self, **kwargs: Any) -> list[dict[str, str]]:
        messages = super().messages(**kwargs)
        modified = copy.deepcopy(messages)
        request = json.loads(modified[1]["content"])
        request.pop("valid_strategy_spec_example", None)
        modified[1]["content"] = json.dumps(
            request,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return modified


def designer_for_arm(arm: str) -> DeepSeekDesigner:
    thinking = False if arm == "no_thinking" else None
    cls = NoExampleDesigner if arm == "no_example" else DeepSeekDesigner
    return cls(**provider_options(thinking_enabled=thinking))


def critic(*, thinking_enabled: bool | None = None) -> DeepSeekCritic:
    return DeepSeekCritic(**provider_options(thinking_enabled=thinking_enabled))


def generate_once(
    designer: DeepSeekDesigner,
    *,
    track: str,
    run_settings: dict[str, Any],
    baseline_results: list[dict[str, Any]],
    iteration: int = 1,
    previous_spec: dict[str, Any] | None = None,
    critique: dict[str, Any] | None = None,
    iteration_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute exactly one provider attempt and one schema validation.

    This is the no-retry arm. It intentionally bypasses both transport/JSON retry
    and Designer semantic retry while reusing the production message and validator.
    """

    messages = designer.messages(
        track=track,
        run_settings=run_settings,
        baseline_results=baseline_results,
        iteration=iteration,
        previous_spec=previous_spec,
        critique=critique,
        iteration_history=iteration_history,
    )
    completed = designer.deepseek.complete_json(
        messages,
        trace_context={
            "ablation_arm": "no_retry",
            "designer_track": track,
            "iteration": iteration,
        },
        max_tokens=4_000,
        empty_error="Designer returned an empty response",
        invalid_error="Designer did not return valid JSON",
        max_attempts=1,
    )
    normalized = designer._validated_proposal(
        completed["payload"],
        track,
        symbol_count=len(run_settings.get("symbols") or []),
        previous_spec=previous_spec,
    )
    return {
        **normalized,
        "usage": completed["usage"],
        "trace": completed["trace"],
        "generation_retries": 0,
    }


def generate_proposal(
    *,
    arm: str,
    track: str,
    run_settings: dict[str, Any],
    baseline_results: list[dict[str, Any]],
    iteration: int = 1,
    previous_spec: dict[str, Any] | None = None,
    critique: dict[str, Any] | None = None,
    iteration_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    designer = designer_for_arm(arm)
    if arm == "no_retry":
        return generate_once(
            designer,
            track=track,
            run_settings=run_settings,
            baseline_results=baseline_results,
            iteration=iteration,
            previous_spec=previous_spec,
            critique=critique,
            iteration_history=iteration_history,
        )
    return designer.generate(
        track=track,
        run_settings=run_settings,
        baseline_results=baseline_results,
        iteration=iteration,
        previous_spec=previous_spec,
        critique=critique,
        iteration_history=iteration_history,
    )
