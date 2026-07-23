from __future__ import annotations

import json
from typing import Any

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.prompts import (
    AGENT_CAPABILITY_CONTRACT,
    DESIGN_OUTPUT_SCHEMA,
    DESIGNER_SYSTEM_PROMPT,
    QC_TEMPLATE,
    TRACK_BRIEFS,
    TRACK_RECIPES,
)


class DeepSeekDesigner:
    def __init__(self, *, lean_documentation: str, **client_options: Any) -> None:
        self.lean_documentation = lean_documentation
        self.deepseek = DeepSeekJSONClient(**client_options)

    def health(self) -> dict[str, Any]:
        return {
            **self.deepseek.health(),
            "documentation_bytes": len(self.lean_documentation.encode("utf-8")),
            "prompt_reference_mode": "compact_capability_contract",
            "prompt_contract_version": "agent-capability-v3",
        }

    @staticmethod
    def _validated_design(payload: dict[str, Any], track: str) -> dict[str, Any]:
        design = payload.get("design")
        if not isinstance(design, dict):
            raise ValueError("DeepSeek response must contain one design object")
        required_strings = (
            "strategy_name",
            "track",
            "thesis",
            "selection_rule",
            "rebalance_rule",
        )
        for key in required_strings:
            if not isinstance(design.get(key), str) or not design[key].strip():
                raise ValueError(f"design.{key} must be a non-empty string")
        if design["track"] != track:
            raise ValueError(f"design.track must be exactly {track}")
        for key in ("signals", "features", "risk_controls", "causal_chain"):
            values = design.get(key)
            if (
                not isinstance(values, list)
                or (key != "features" and not values)
                or not all(isinstance(item, str) and item.strip() for item in values)
            ):
                raise ValueError(f"design.{key} must be a list of non-empty strings")
        if len(design["risk_controls"]) < 2:
            raise ValueError("design.risk_controls must contain at least two controls")
        if track == "Traditional":
            if design.get("training_plan") is not None or design["features"]:
                raise ValueError(
                    "Traditional design must use null training_plan and empty features"
                )
        elif (
            not isinstance(design.get("training_plan"), str)
            or not design["training_plan"].strip()
            or not design["features"]
        ):
            raise ValueError(
                f"{track} design requires a training_plan and exact feature list"
            )
        spec = design.get("strategy_spec")
        if not isinstance(spec, dict):
            raise ValueError("design.strategy_spec must be one bounded object")
        required_spec = {
            "signal_family",
            "model_family",
            "rebalance_frequency",
            "lookback_days",
            "label_horizon_days",
            "top_k",
            "weighting",
        }
        if set(spec) != required_spec:
            raise ValueError(
                "design.strategy_spec must contain exactly: "
                + ", ".join(sorted(required_spec))
            )
        if spec["signal_family"] not in {
            None,
            "momentum",
            "mean_reversion",
            "trend",
            "volatility",
        }:
            raise ValueError("design.strategy_spec.signal_family is unsupported")
        if spec["model_family"] not in {
            None,
            "gradient_boosting",
            "random_forest",
        }:
            raise ValueError("design.strategy_spec.model_family is unsupported")
        if spec["rebalance_frequency"] not in {"weekly", "monthly"}:
            raise ValueError("design.strategy_spec.rebalance_frequency is unsupported")
        if spec["lookback_days"] not in {63, 126, 252}:
            raise ValueError("design.strategy_spec.lookback_days must be 63, 126, or 252")
        if spec["label_horizon_days"] not in {None, 10, 21}:
            raise ValueError(
                "design.strategy_spec.label_horizon_days must be null, 10, or 21"
            )
        if (
            not isinstance(spec["top_k"], int)
            or isinstance(spec["top_k"], bool)
            or not 2 <= spec["top_k"] <= 5
        ):
            raise ValueError("design.strategy_spec.top_k must be an integer from 2 to 5")
        if spec["weighting"] not in {"equal", "inverse_volatility"}:
            raise ValueError("design.strategy_spec.weighting is unsupported")
        if track == "Traditional" and (
            spec["model_family"] is not None
            or spec["label_horizon_days"] is not None
            or spec["signal_family"] is None
        ):
            raise ValueError("Traditional strategy_spec requires a signal and no model")
        if track == "ML" and (
            spec["model_family"] is None
            or spec["label_horizon_days"] is None
            or spec["signal_family"] is not None
        ):
            raise ValueError("ML strategy_spec requires a model and no non-ML signal")
        if track == "Hybrid" and (
            spec["model_family"] is None
            or spec["label_horizon_days"] is None
            or spec["signal_family"] is None
        ):
            raise ValueError("Hybrid strategy_spec requires both model and signal")
        return design

    def messages(
        self,
        *,
        track: str,
        run_settings: dict[str, Any],
        baseline_results: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        if track not in TRACK_BRIEFS:
            raise ValueError(f"unknown Designer track: {track}")
        request = {
            "designer_track": track,
            "design_brief": TRACK_BRIEFS[track],
            "run_settings": run_settings,
            "baseline_results": baseline_results,
            "output_schema": DESIGN_OUTPUT_SCHEMA,
        }
        prompt = (
            f"{AGENT_CAPABILITY_CONTRACT}\n\n"
            f"{TRACK_RECIPES[track]}\n\n"
            "ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE\n\n"
            f"{QC_TEMPLATE}\n\n"
            "DESIGNER REQUEST\n\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}\n\n"
            "First make the structured design internally consistent, then implement "
            "exactly that design in source_code. Replace the template comments; return "
            "the complete file. Baseline results are public evidence, not targets that "
            "must be beaten, and no Human strategy information is available."
        )
        return [
            {"role": "system", "content": DESIGNER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def generate(
        self,
        *,
        track: str,
        run_settings: dict[str, Any],
        baseline_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        completed = self.deepseek.complete_json(
            self.messages(
                track=track,
                run_settings=run_settings,
                baseline_results=baseline_results,
            ),
            trace_context={
                "designer_track": track,
                "run_settings": run_settings,
                "baseline_results": baseline_results,
                "context_manifest": {
                    "includes": [
                        "public_baselines",
                        "run_settings",
                        "agent_capability_contract_v2",
                    ],
                    "excludes": [
                        "human_source",
                        "human_settings",
                        "human_results",
                        "education_output",
                    ],
                },
            },
            max_tokens=12_000,
            empty_error="DeepSeek returned an empty response",
            invalid_error="DeepSeek did not return valid JSON",
        )
        payload = completed["payload"]
        try:
            design = self._validated_design(payload, track)
        except ValueError as exc:
            raise DeepSeekCallError(
                str(exc),
                trace=completed["trace"],
            ) from exc
        if not isinstance(payload.get("source_code"), str):
            raise DeepSeekCallError(
                "DeepSeek response must contain one source_code string",
                trace=completed["trace"],
            )
        source_code = payload["source_code"].strip()
        if not source_code:
            raise DeepSeekCallError(
                "DeepSeek returned empty source_code",
                trace=completed["trace"],
            )
        return {
            "design": design,
            "source_code": source_code,
            "usage": completed["usage"],
            "trace": completed["trace"],
        }
