from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.prompts import (
    DESIGNER_SYSTEM_PROMPT,
    PARAMETER_RULES,
    PROPOSAL_SHAPE,
    TRACK_BRIEFS,
    TRACK_SPEC_EXAMPLES,
)
from app.schemas import DesignRationale, StrategyTemplateSpec


def _compact_baselines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.get("name"),
            "family": item.get("family"),
            "summary": {
                key: (item.get("summary") or {}).get(key)
                for key in (
                    "cagr",
                    "sharpe_ratio",
                    "maximum_drawdown",
                    "end_equity",
                )
            },
            "public_ranks": item.get("public_ranks") or {},
            "lesson": item.get("public_lesson") or {},
        }
        for item in items
    ]


class DeepSeekDesigner:
    def __init__(self, **client_options: Any) -> None:
        self.deepseek = DeepSeekJSONClient(**client_options)

    def health(self) -> dict[str, Any]:
        return {
            **self.deepseek.health(),
            "output_mode": "strategy_parameters_only",
            "prompt_contract_version": "template-designer-v1",
        }

    @staticmethod
    def _validated_proposal(
        payload: dict[str, Any],
        track: str,
        *,
        symbol_count: int,
        previous_spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Designer output must be a JSON object")
        try:
            spec = StrategyTemplateSpec.model_validate(payload.get("strategy_spec"))
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        if spec.track != track:
            raise ValueError(f"strategy_spec.track must be exactly {track}")
        if spec.selection.top_k > symbol_count:
            raise ValueError("selection.top_k cannot exceed the run symbol count")

        # The explanation is presentation metadata, not executable strategy input.
        # Normalize harmless verbosity instead of throwing away a valid strategy
        # specification and asking the model to regenerate financial parameters.
        raw_design = payload.get("design")
        if not isinstance(raw_design, dict):
            raw_design = {}

        def compact_strings(value: Any, limit: int) -> list[str]:
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                return []
            return [
                str(item).strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ][:limit]

        references = compact_strings(raw_design.get("reference_baselines"), 2)
        differences = compact_strings(raw_design.get("differentiation"), 3)
        hypothesis = str(raw_design.get("improvement_hypothesis") or "").strip()
        tradeoff = str(raw_design.get("expected_tradeoff") or "").strip()
        normalized_design = {
            "reference_baselines": references or ["Public baseline set"],
            "improvement_hypothesis": (
                hypothesis
                if len(hypothesis) >= 10
                else spec.thesis
            ),
            "differentiation": differences
            or ["Uses a distinct bounded template parameter configuration."],
            "expected_tradeoff": (
                tradeoff
                if len(tradeoff) >= 10
                else "Potential return improvement may come with higher estimation risk."
            ),
        }
        try:
            design = DesignRationale.model_validate(normalized_design)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        normalized = {
            "design": design.model_dump(mode="json"),
            "strategy_spec": spec.model_dump(mode="json"),
        }
        if previous_spec is not None:
            normalized_previous = StrategyTemplateSpec.model_validate(
                previous_spec
            ).model_dump(mode="json")
            if normalized["strategy_spec"] == normalized_previous:
                raise ValueError(
                    "a revision must change at least one strategy parameter"
                )
        return normalized

    def messages(
        self,
        *,
        track: str,
        run_settings: dict[str, Any],
        baseline_results: list[dict[str, Any]],
        iteration: int = 1,
        previous_spec: dict[str, Any] | None = None,
        critique: dict[str, Any] | None = None,
        iteration_history: list[dict[str, Any]] | None = None,
        battle_memory: dict[str, Any] | None = None,
        incumbent: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        if track not in TRACK_BRIEFS:
            raise ValueError(f"unknown Designer track: {track}")
        track_coach_directive = next(
            (
                lesson
                for lesson in (battle_memory or {}).get("track_lessons", [])
                if lesson.get("track") == track
            ),
            None,
        )
        request = {
            "assigned_track": track,
            "iteration": iteration,
            "track_rule": TRACK_BRIEFS[track],
            "run_contract": {
                key: run_settings.get(key)
                for key in (
                    "symbols",
                    "start_date",
                    "end_date",
                    "benchmark",
                    "transaction_cost_bps",
                    "slippage_bps",
                )
            },
            "public_baselines": _compact_baselines(baseline_results),
            "previous_strategy_spec": previous_spec,
            "critic_report": critique,
            "prior_iteration_results": iteration_history or [],
            "prior_round_ai_coach_memory": battle_memory,
            "assigned_track_coach_directive": track_coach_directive,
            "battle_track_incumbent": (
                {
                    "round_number": incumbent.get("_battle_round_number"),
                    "strategy_spec": incumbent.get("strategy_spec"),
                    "summary": incumbent.get("summary"),
                }
                if incumbent
                else None
            ),
            "parameter_rules": PARAMETER_RULES,
            "valid_strategy_spec_example": TRACK_SPEC_EXAMPLES[track],
            "output_shape": PROPOSAL_SHAPE,
        }
        return [
            {"role": "system", "content": DESIGNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(request, ensure_ascii=False, separators=(",", ":")),
            },
        ]

    def generate(
        self,
        *,
        track: str,
        run_settings: dict[str, Any],
        baseline_results: list[dict[str, Any]],
        iteration: int = 1,
        previous_spec: dict[str, Any] | None = None,
        critique: dict[str, Any] | None = None,
        iteration_history: list[dict[str, Any]] | None = None,
        battle_memory: dict[str, Any] | None = None,
        incumbent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_messages = self.messages(
            track=track,
            run_settings=run_settings,
            baseline_results=baseline_results,
            iteration=iteration,
            previous_spec=previous_spec,
            critique=critique,
            iteration_history=iteration_history,
            battle_memory=battle_memory,
            incumbent=incumbent,
        )
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        semantic_attempts: list[dict[str, Any]] = []
        previous_error: str | None = None
        model_calls_used = 0
        for semantic_attempt in range(2):
            messages = list(base_messages)
            if previous_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous JSON failed the parameter schema: "
                            f"{previous_error}. Return the complete corrected JSON object. "
                            "Do not return code or a patch. Copy this exact nesting and "
                            "replace only values or repeated list items:\n"
                            f"{json.dumps(TRACK_SPEC_EXAMPLES[track], ensure_ascii=False)}"
                        ),
                    }
                )
            completed = self.deepseek.complete_json(
                messages,
                trace_context={
                    "designer_track": track,
                    "iteration": iteration,
                    "previous_schema_error": previous_error,
                    "context_manifest": {
                        "includes": [
                            "public_baselines",
                            "run_contract",
                            "template_dsl",
                            "prior_ai_iterations",
                            "critic_report",
                            "prior_round_ai_coach_memory",
                            "assigned_track_coach_directive",
                            "battle_track_incumbent",
                        ],
                        "excludes": [
                            "human_source",
                            "human_results",
                            "lean_documentation",
                            "python_template",
                        ],
                    },
                },
                max_tokens=4_000,
                empty_error="Designer returned an empty response",
                invalid_error="Designer did not return valid JSON",
                max_attempts=2 - model_calls_used,
            )
            model_calls_used += len(completed["trace"].get("attempts", []))
            for key in total_usage:
                total_usage[key] += int(completed["usage"].get(key, 0) or 0)
            try:
                normalized = self._validated_proposal(
                    completed["payload"],
                    track,
                    symbol_count=len(run_settings.get("symbols") or []),
                    previous_spec=previous_spec,
                )
            except ValueError as exc:
                previous_error = str(exc)
                semantic_attempts.append(
                    {
                        "attempt": semantic_attempt + 1,
                        "status": "schema_failed",
                        "error": previous_error,
                        "call": completed["trace"],
                    }
                )
                if semantic_attempt == 0 and model_calls_used < 2:
                    continue
                trace = dict(completed["trace"])
                trace["semantic_validation_attempts"] = semantic_attempts
                trace["semantic_retry_count"] = semantic_attempt
                trace["usage"] = total_usage
                raise DeepSeekCallError(previous_error, trace=trace) from exc
            semantic_attempts.append(
                {
                    "attempt": semantic_attempt + 1,
                    "status": "passed",
                    "error": None,
                    "call": completed["trace"],
                }
            )
            trace = dict(completed["trace"])
            trace["semantic_validation_attempts"] = semantic_attempts
            trace["semantic_retry_count"] = semantic_attempt
            trace["usage"] = total_usage
            return {
                **normalized,
                "usage": total_usage,
                "trace": trace,
                "generation_retries": semantic_attempt,
            }
        raise AssertionError("unreachable Designer semantic retry state")
