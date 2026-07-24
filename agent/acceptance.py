from __future__ import annotations

import json
from typing import Any

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.prompts import (
    ACCEPTANCE_CHECK_IDS,
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
        previous_acceptance: dict[str, Any] | None = None,
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
            "previous_acceptance": previous_acceptance,
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
        base_messages = self.messages(**context)
        trace_context = {
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
                "previous_acceptance": context.get("previous_acceptance"),
        }
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        model_calls_used = 0
        previous_error: str | None = None
        semantic_attempts: list[dict[str, Any]] = []
        for semantic_attempt in range(2):
            messages = list(base_messages)
            if previous_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous JSON was not a coherent Acceptance report: "
                            f"{previous_error}. Return the complete corrected report once, "
                            "with decision accept/revise and exactly A1-A5."
                        ),
                    }
                )
            completed = self.deepseek.complete_json(
                messages,
                trace_context={
                    **trace_context,
                    "semantic_acceptance_attempt": semantic_attempt + 1,
                    "previous_schema_error": previous_error,
                },
                max_tokens=6_000,
                empty_error="DeepSeek acceptance agent returned an empty response",
                invalid_error="DeepSeek acceptance agent did not return valid JSON",
                max_attempts=2 - model_calls_used,
            )
            model_calls_used += len(completed["trace"].get("attempts", []))
            for key in total_usage:
                total_usage[key] += int(completed["usage"].get(key, 0) or 0)
            try:
                self._validate_report_shape(
                    completed["payload"],
                    behavior_evidence=context["behavior_evidence"],
                    run_settings=context["run_settings"],
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
            trace["usage"] = total_usage
            return {
                "report": completed["payload"],
                "usage": total_usage,
                "trace": trace,
            }
        raise AssertionError("unreachable Acceptance semantic retry state")

    @staticmethod
    def _validate_report_shape(
        report: dict[str, Any],
        *,
        behavior_evidence: dict[str, Any],
        run_settings: dict[str, Any],
    ) -> None:
        if report.get("decision") not in {"accept", "revise"}:
            raise ValueError("decision must be accept or revise")
        checks = report.get("checks")
        if not isinstance(checks, list) or len(checks) != 5:
            raise ValueError("checks must contain exactly A1 through A5")
        by_id = {
            item.get("id"): item
            for item in checks
            if isinstance(item, dict)
        }
        if set(by_id) != set(ACCEPTANCE_CHECK_IDS):
            raise ValueError("checks must contain each of A1 through A5 once")
        if any(item.get("status") not in {"pass", "fail"} for item in by_id.values()):
            raise ValueError("every check status must be pass or fail")
        activity = (
            int(behavior_evidence.get("filled_order_count") or 0) > 0
            and int(behavior_evidence.get("invested_snapshot_count") or 0) > 0
            and float(behavior_evidence.get("max_gross_exposure") or 0) > 0
        )
        if by_id["A1"].get("status") != ("pass" if activity else "fail"):
            raise ValueError("A1 contradicts authoritative runtime activity")
        allowed = {
            str(symbol).strip().upper()
            for symbol in run_settings.get("symbols", [])
            if str(symbol).strip()
        }
        traded = {
            str(symbol).strip().upper()
            for symbol in behavior_evidence.get("traded_symbols", [])
            if str(symbol).strip()
        }
        expected_a5 = "fail" if traded - allowed else "pass"
        if by_id["A5"].get("status") != expected_a5:
            raise ValueError("A5 contradicts authoritative traded-symbol evidence")
        statuses = [by_id[key].get("status") for key in ACCEPTANCE_CHECK_IDS]
        repair = report.get("repair_request")
        if report["decision"] == "accept":
            if any(status != "pass" for status in statuses) or repair is not None:
                raise ValueError("accept requires all checks pass and null repair_request")
        elif (
            all(status == "pass" for status in statuses)
            or not isinstance(repair, str)
            or not repair.strip()
        ):
            raise ValueError("revise requires a failed check and repair_request")
