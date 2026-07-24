from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.designer import _compact_baselines
from agent.prompts import CRITIQUE_SHAPE, CRITIC_SYSTEM_PROMPT
from app.schemas import CritiqueReport


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
                max_attempts=1,
            )
            for key in total_usage:
                total_usage[key] += int(completed["usage"].get(key, 0) or 0)
            try:
                report = CritiqueReport.model_validate(completed["payload"])
                if report.iteration != iteration:
                    raise ValueError(
                        f"Critic iteration must be exactly {iteration}"
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
                "usage": total_usage,
                "trace": trace,
            }
        raise AssertionError("unreachable Critic semantic retry state")
