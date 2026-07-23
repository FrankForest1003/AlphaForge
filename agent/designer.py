from __future__ import annotations

import json
from typing import Any

from agent.client import DeepSeekJSONClient
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
            "Keep the UserStrategy class and AlphaForgeBaseAlgorithm integration. "
            "Use the run_settings parameters instead of replacing the selected candidate "
            "pool, dates, cash, benchmark, fees, or slippage with private constants. "
            "Use DataFrame history calls consistently, keep total absolute target weights "
            "at or below self.target_gross, and do not reduce the inherited cash buffer. "
            "Use af_rebalance_to_weights for long-only Daily basket rebalances so "
            "reductions fill before purchases are sized. Replace the template comments "
            "with the assigned strategy. The source_code value must contain the complete "
            "Python file."
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
            max_tokens=16_000,
            empty_error="DeepSeek returned an empty response",
            invalid_error="DeepSeek did not return valid JSON",
        )
        payload = completed["payload"]
        if not isinstance(payload.get("source_code"), str):
            raise ValueError("DeepSeek response must contain one source_code string")
        source_code = payload["source_code"].strip()
        if not source_code:
            raise ValueError("DeepSeek returned empty source_code")
        return {"source_code": source_code, "usage": completed["usage"]}
