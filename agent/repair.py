from __future__ import annotations

import json
from typing import Any

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.prompts import QC_TEMPLATE, REPAIR_SYSTEM_PROMPT, TRACK_BRIEFS


class DeepSeekRepairAgent:
    def __init__(self, *, lean_documentation: str, **client_options: Any) -> None:
        self.lean_documentation = lean_documentation
        self.deepseek = DeepSeekJSONClient(**client_options)

    def messages(
        self,
        *,
        track: str,
        run_settings: dict[str, Any],
        baseline_results: list[dict[str, Any]],
        source_code: str,
        worker_result: dict[str, Any],
        lean_console_log: str,
        repair_attempt: int,
        repair_trigger: str,
        acceptance_report: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        if track not in TRACK_BRIEFS:
            raise ValueError(f"unknown Designer track: {track}")
        if repair_trigger not in {"runtime_failure", "acceptance_revision"}:
            raise ValueError(f"unknown repair trigger: {repair_trigger}")
        request = {
            "designer_track": track,
            "design_brief": TRACK_BRIEFS[track],
            "repair_attempt": repair_attempt,
            "run_settings": run_settings,
            "baseline_results": baseline_results,
            "submitted_source_code": source_code,
            "worker_result": worker_result,
            "lean_console_log": lean_console_log,
            "repair_trigger": repair_trigger,
            "output": {"source_code": "complete repaired runnable Python source"},
        }
        if acceptance_report is not None:
            request["acceptance_report"] = acceptance_report
        prompt = (
            "ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE\n\n"
            f"{QC_TEMPLATE}\n\n"
            "OFFICIAL QUANTCONNECT WRITING ALGORITHMS DOCUMENTATION\n\n"
            f"{self.lean_documentation}\n\n"
            "REPAIR REQUEST\n\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}\n\n"
            "Return the complete repaired file, not a patch. Keep UserStrategy and "
            "AlphaForgeBaseAlgorithm. Preserve the assigned strategy idea and all seven "
            "shared run settings. Inspect the entire source for defects related to the "
            "observed failure. Use DataFrame history calls consistently, keep total "
            "absolute target weights at or below self.target_gross, and do not reduce the "
            "inherited cash buffer. Use af_rebalance_to_weights for long-only Daily "
            "basket rebalances so reductions fill before purchases are sized."
        )
        if acceptance_report is not None:
            prompt += (
                " Fix the complete causal chain identified by the acceptance report. "
                "Do not chase profitability or baseline performance, and do not submit "
                "meaningless orders merely to satisfy the activity check."
            )
        return [
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def repair(self, **context: Any) -> dict[str, Any]:
        trace_context = {
            "designer_track": context["track"],
            "repair_attempt": context["repair_attempt"],
            "run_settings": context["run_settings"],
            "baseline_results": context["baseline_results"],
            "submitted_source_code": context["source_code"],
            "worker_result": context["worker_result"],
            "lean_console_log": context["lean_console_log"],
            "repair_trigger": context["repair_trigger"],
        }
        if context.get("acceptance_report") is not None:
            trace_context["acceptance_report"] = context["acceptance_report"]
        completed = self.deepseek.complete_json(
            self.messages(**context),
            trace_context=trace_context,
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
