from __future__ import annotations

import json
from typing import Any

from agent.client import DeepSeekJSONClient
from agent.prompts import (
    ACCEPTANCE_RULES,
    ACCEPTANCE_SYSTEM_PROMPT,
    TRACK_BRIEFS,
)


class DeepSeekAcceptanceAgent:
    def __init__(self, **client_options: Any) -> None:
        self.deepseek = DeepSeekJSONClient(**client_options)

    def health(self) -> dict[str, Any]:
        return self.deepseek.health()

    def messages(
        self,
        *,
        track: str,
        run_settings: dict[str, Any],
        critical_log_evidence: str,
        source_code: str,
        worker_result: dict[str, Any],
        lean_console_log: str,
        behavior_evidence: dict[str, Any],
        acceptance_attempt: int,
        candidate_design: dict[str, Any] | None = None,
        preflight_report: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        if track not in TRACK_BRIEFS:
            raise ValueError(f"unknown Designer track: {track}")
        request = {
            "designer_track": track,
            "track_requirement": TRACK_BRIEFS[track],
            "behavior_gate": {
                "required": (
                    "filled_order_count > 0 and invested_snapshot_count > 0 "
                    "and max_gross_exposure > 0"
                ),
                "observed": behavior_evidence,
            },
            "critical_log_evidence": critical_log_evidence,
            "run_settings": run_settings,
            "candidate_design": candidate_design,
            "deterministic_preflight": preflight_report,
            "source_code": source_code,
            "worker_result": worker_result,
            "lean_console_log_excerpt": lean_console_log,
            "behavior_evidence": behavior_evidence,
            "acceptance_attempt": acceptance_attempt,
            "output": {
                "decision": "accept or revise",
                "checks": [
                    {
                        "id": "exactly one of A1 through A5",
                        "status": "pass or fail",
                        "evidence": ["specific source, log, or behavior fact"],
                        "reason": "why the check passes or fails",
                    }
                ],
                "repair_request": "null for accept; non-empty string for revise",
            },
        }
        prompt = (
            f"{ACCEPTANCE_RULES}\n\n"
            "ACCEPTANCE REQUEST\n\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}"
        )
        return [
            {"role": "system", "content": ACCEPTANCE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def evaluate(self, **context: Any) -> dict[str, Any]:
        completed = self.deepseek.complete_json(
            self.messages(**context),
            trace_context={
                "designer_track": context["track"],
                "run_settings": context["run_settings"],
                "critical_log_evidence": context["critical_log_evidence"],
                "source_code": context["source_code"],
                "worker_result": context["worker_result"],
                "lean_console_log_excerpt": context["lean_console_log"],
                "behavior_evidence": context["behavior_evidence"],
                "acceptance_attempt": context["acceptance_attempt"],
                "candidate_design": context.get("candidate_design"),
                "deterministic_preflight": context.get("preflight_report"),
            },
            max_tokens=6_000,
            empty_error="DeepSeek acceptance agent returned an empty response",
            invalid_error="DeepSeek acceptance agent did not return valid JSON",
        )
        return {
            "report": completed["payload"],
            "usage": completed["usage"],
            "trace": completed["trace"],
        }
