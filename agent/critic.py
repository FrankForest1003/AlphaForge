from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.designer import _compact_baselines
from agent.prompts import CRITIQUE_SHAPE, CRITIC_SYSTEM_PROMPT
from app.schemas import CritiqueReport


ACTIVE_PARAMETER_PREFIXES = {
    "Traditional": (
        "signal.",
        "selection.top_k",
        "selection.require_positive_score",
        "portfolio.",
        "schedule.",
        "risk.",
    ),
    "ML": (
        "model.",
        "selection.top_k",
        "selection.require_positive_score",
        "portfolio.",
        "schedule.",
        "risk.",
    ),
    "Hybrid": (
        "signal.",
        "model.",
        "selection.",
        "portfolio.",
        "schedule.",
        "risk.",
    ),
}

TRACK_RUNTIME_EXPECTATIONS = {
    "Traditional": (
        "ML training, prediction, and hybrid-decision counters should be zero; "
        "the transparent signal must link to targets."
    ),
    "ML": (
        "signal and hybrid-decision counters should be zero; ML training, "
        "prediction, and prediction-to-target links must be positive."
    ),
    "Hybrid": (
        "signal, ML training, prediction, and hybrid-decision link counters must "
        "all be positive."
    ),
}


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    summary = item.get("summary")
    return summary if isinstance(summary, dict) else {}


def build_metric_comparisons(
    current_result: dict[str, Any],
    baseline_results: list[dict[str, Any]],
    iteration_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Precompute comparison arithmetic so the Critic only interprets facts."""

    current = _summary(current_result)
    metrics = {
        "sharpe_ratio": "higher",
        "cagr": "higher",
        "maximum_drawdown": "lower",
    }
    comparisons: dict[str, Any] = {}
    for metric, better in metrics.items():
        current_value = _finite_number(current.get(metric))
        baseline_values = [
            (str(item.get("name") or "Unnamed baseline"), _finite_number(_summary(item).get(metric)))
            for item in baseline_results
        ]
        baseline_values = [
            (name, value) for name, value in baseline_values if value is not None
        ]
        if baseline_values:
            best_name, best_value = (
                max(baseline_values, key=lambda pair: pair[1])
                if better == "higher"
                else min(baseline_values, key=lambda pair: pair[1])
            )
        else:
            best_name, best_value = None, None
        previous_value = None
        if iteration_history:
            previous_value = _finite_number(
                _summary(iteration_history[-1]).get(metric)
            )
        comparisons[metric] = {
            "better_direction": better,
            "current": current_value,
            "best_public_baseline": best_value,
            "best_public_baseline_name": best_name,
            "current_minus_best_public": (
                current_value - best_value
                if current_value is not None and best_value is not None
                else None
            ),
            "previous_iteration": previous_value,
            "current_minus_previous": (
                current_value - previous_value
                if current_value is not None and previous_value is not None
                else None
            ),
        }
    return comparisons


def _normalize_suggestion_field(field: str) -> str:
    prefix = "strategy_spec."
    return field[len(prefix):] if field.startswith(prefix) else field


class DeepSeekCritic:
    def __init__(self, **client_options: Any) -> None:
        self.deepseek = DeepSeekJSONClient(**client_options)

    def health(self) -> dict[str, Any]:
        return {
            **self.deepseek.health(),
            "output_mode": "performance_critique_only",
            "prompt_contract_version": "template-critic-v1",
        }

    def evaluate(
        self,
        *,
        track: str,
        iteration: int,
        strategy_spec: dict[str, Any],
        iteration_result: dict[str, Any],
        baseline_results: list[dict[str, Any]],
        iteration_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        request = {
            "assigned_track": track,
            "iteration": iteration,
            "strategy_spec": strategy_spec,
            "current_result": iteration_result,
            "prior_iterations": iteration_history,
            "public_baselines": _compact_baselines(baseline_results),
            "computed_comparisons": build_metric_comparisons(
                iteration_result,
                baseline_results,
                iteration_history,
            ),
            "active_parameter_prefixes": ACTIVE_PARAMETER_PREFIXES[track],
            "track_runtime_expectations": TRACK_RUNTIME_EXPECTATIONS[track],
            "output_shape": CRITIQUE_SHAPE,
        }
        messages = [
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(request, ensure_ascii=False, separators=(",", ":")),
            },
        ]
        previous_error: str | None = None
        attempts: list[dict[str, Any]] = []
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        for semantic_attempt in range(2):
            attempt_messages = list(messages)
            if previous_error:
                attempt_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous critique failed the output schema: "
                            f"{previous_error}. Return one complete corrected critique "
                            "object and no strategy parameters or code."
                        ),
                    }
                )
            completed = self.deepseek.complete_json(
                attempt_messages,
                trace_context={
                    "critic_track": track,
                    "iteration": iteration,
                    "previous_schema_error": previous_error,
                    "context_manifest": {
                        "includes": [
                            "current_parameters",
                            "current_performance",
                            "prior_ai_iterations",
                            "public_baselines",
                        ],
                        "excludes": [
                            "source_code",
                            "lean_documentation",
                            "human_source",
                            "human_results",
                        ],
                    },
                },
                max_tokens=2_500,
                empty_error="Critic returned an empty response",
                invalid_error="Critic did not return valid JSON",
                max_attempts=2,
            )
            for key in total_usage:
                total_usage[key] += int(completed["usage"].get(key, 0) or 0)
            try:
                report = CritiqueReport.model_validate(completed["payload"])
                if report.iteration != iteration:
                    raise ValueError(
                        f"Critic iteration must be exactly {iteration}"
                    )
                allowed = ACTIVE_PARAMETER_PREFIXES[track]
                accepted = []
                discarded = []
                for suggestion in report.recommended_changes:
                    field = _normalize_suggestion_field(suggestion.field)
                    normalized = suggestion.model_copy(update={"field": field})
                    if any(
                        (
                            field.startswith(prefix)
                            if prefix.endswith(".")
                            else field == prefix
                        )
                        for prefix in allowed
                    ):
                        accepted.append(normalized)
                    else:
                        discarded.append(normalized.model_dump(mode="json"))
                report = report.model_copy(
                    update={"recommended_changes": accepted}
                )
            except (ValidationError, ValueError) as exc:
                previous_error = str(exc)
                attempts.append(
                    {
                        "attempt": semantic_attempt + 1,
                        "status": "schema_failed",
                        "error": previous_error,
                        "call": completed["trace"],
                    }
                )
                if semantic_attempt == 0:
                    continue
                trace = dict(completed["trace"])
                trace["semantic_validation_attempts"] = attempts
                trace["usage"] = total_usage
                raise DeepSeekCallError(
                    f"Critic response failed schema validation: {previous_error}",
                    trace=trace,
                ) from exc
            attempts.append(
                {
                    "attempt": semantic_attempt + 1,
                    "status": "passed",
                    "error": None,
                    "call": completed["trace"],
                }
            )
            trace = dict(completed["trace"])
            trace["semantic_validation_attempts"] = attempts
            trace["usage"] = total_usage
            return {
                "report": report.model_dump(mode="json"),
                "discarded_recommendations": discarded,
                "usage": total_usage,
                "trace": trace,
            }
        raise AssertionError("unreachable Critic semantic retry state")
