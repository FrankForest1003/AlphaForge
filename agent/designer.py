from __future__ import annotations

import json
from typing import Any

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.prompts import (
    DESIGNER_SYSTEM_PROMPT,
    QC_TEMPLATE,
    TRACK_BRIEFS,
)


class DeepSeekDesigner:
    def __init__(self, *, lean_documentation: str, **client_options: Any) -> None:
        self.lean_documentation = lean_documentation
        self.deepseek = DeepSeekJSONClient(**client_options)

    def health(self) -> dict[str, Any]:
        return {
            **self.deepseek.health(),
            "documentation_bytes": len(self.lean_documentation.encode("utf-8")),
        }

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
            "output": {"source_code": "complete runnable Python source"},
        }
        prompt = (
            "ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE\n\n"
            f"{QC_TEMPLATE}\n\n"
            "OFFICIAL QUANTCONNECT WRITING ALGORITHMS DOCUMENTATION\n\n"
            f"{self.lean_documentation}\n\n"
            "DESIGNER REQUEST\n\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}\n\n"
            "Keep the UserStrategy class and use standard QuantConnect lifecycle "
            "callbacks such as initialize, on_data, on_order_event, and "
            "on_end_of_algorithm whenever they are needed. "
            "Use the run_settings parameters instead of replacing the selected candidate "
            "pool, dates, cash, benchmark, fees, or slippage with private constants. "
            "Use the Daily data capability and DataFrame history lookup shown in the "
            "template consistently. Record each transparent signal that reaches a "
            "decision with af_record_signal. For ML and Hybrid, record successful model "
            "fits and produced predictions with af_record_ml_training and "
            "af_record_ml_prediction. Choose and implement portfolio "
            "sizing, cash reserve, and order handling for the assigned strategy. Account "
            "for configured fees and slippage and for prices changing between sizing and "
            "execution. For a Daily-resolution basket rotation whose purchases use "
            "capital released by removals or reductions, use the template's "
            "self.af_rebalance_daily_weights helper with the strategy's complete desired "
            "long-only weight map. Align the signal or prediction horizon, target-update "
            "cadence, and execution cadence so each staged rotation can reach completion "
            "before the next target update. Replace the template comments with the assigned strategy. The "
            "source_code value must contain the complete Python file."
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
            },
            max_tokens=16_000,
            empty_error="DeepSeek returned an empty response",
            invalid_error="DeepSeek did not return valid JSON",
        )
        payload = completed["payload"]
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
            "source_code": source_code,
            "usage": completed["usage"],
            "trace": completed["trace"],
        }
