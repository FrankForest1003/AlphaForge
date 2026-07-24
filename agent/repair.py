from __future__ import annotations

import json
from typing import Any

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from agent.prompts import (
    AGENT_CAPABILITY_CONTRACT,
    QC_TEMPLATE,
    REPAIR_SYSTEM_PROMPT,
    TRACK_BRIEFS,
    TRACK_RECIPES,
)


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
        validation_report: dict[str, Any] | None = None,
        candidate_design: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        if track not in TRACK_BRIEFS:
            raise ValueError(f"unknown Designer track: {track}")
        if repair_trigger not in {
            "static_validation",
            "runtime_failure",
            "acceptance_revision",
        }:
            raise ValueError(f"unknown repair trigger: {repair_trigger}")
        request = {
            "designer_track": track,
            "design_brief": TRACK_BRIEFS[track],
            "repair_attempt": repair_attempt,
            "run_settings": run_settings,
            "baseline_results": baseline_results,
            "submitted_source_code": source_code,
            "worker_result": worker_result,
            "lean_console_log_excerpt": lean_console_log,
            "repair_trigger": repair_trigger,
            "validation_report": validation_report,
            "candidate_design": candidate_design,
            "output_schema": {
                "change_summary": [
                    "one to three specific changes tied to observed evidence"
                ],
                "first_interrupted_stage": "the single stage repaired",
                "source_code": "complete repaired runnable Python source",
            },
        }
        if acceptance_report is not None:
            request["acceptance_report"] = acceptance_report
        prompt = (
            f"{AGENT_CAPABILITY_CONTRACT}\n\n"
            f"{TRACK_RECIPES[track]}\n\n"
            "ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE\n\n"
            f"{QC_TEMPLATE}\n\n"
            "REPAIR REQUEST\n\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}\n\n"
            "Return the complete repaired file, not a patch. Tie every change to the "
            "validation diagnostic, LEAN error, or failed acceptance check supplied. "
            "When validation_report contains runtime_failure_evidence, treat its failed "
            "order, OrderEvent, portfolio_before_failure, and log excerpt as authoritative "
            "observations. Do not infer an unrecorded cause; say not observed when the "
            "evidence is absent. If staged rebalances start but do not complete, align the "
            "signal or label horizon and target-update cadence with the multi-bar execution "
            "lifecycle before changing risk exposure. Treat the Backend's deterministic "
            "first interrupted stage and failure_classification as authoritative; an "
            "agent_advisory_repair_request is only a hypothesis. If later stages already "
            "show predictions, targets, or fills, preserve that working schedule and "
            "portfolio logic. When training is the first missing stage, calculate the "
            "history request and every rolling/pct_change/shift/dropna row loss, then fix "
            "the exact early-return or cardinality mismatch instead of moving the schedule. "
            "Do not redesign unrelated working parts and do not claim a fix that is "
            "absent from source_code."
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
            "lean_console_log_excerpt": context["lean_console_log"],
            "repair_trigger": context["repair_trigger"],
        }
        if context.get("acceptance_report") is not None:
            trace_context["acceptance_report"] = context["acceptance_report"]
        if context.get("validation_report") is not None:
            trace_context["validation_report"] = context["validation_report"]
        if context.get("candidate_design") is not None:
            trace_context["candidate_design"] = context["candidate_design"]
        base_messages = self.messages(**context)
        semantic_attempts: list[dict[str, Any]] = []
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        previous_error: str | None = None
        for semantic_attempt in range(2):
            messages = list(base_messages)
            if previous_error is not None:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous repair JSON parsed, but failed AlphaForge "
                            f"semantic validation: {previous_error}\n"
                            "Regenerate the complete repair object once. Return a complete "
                            "changed source_code file, one to three concrete change_summary "
                            "strings, and one non-empty first_interrupted_stage."
                        ),
                    }
                )
            completed = self.deepseek.complete_json(
                messages,
                trace_context={
                    **trace_context,
                    "semantic_repair_attempt": semantic_attempt + 1,
                    "previous_schema_error": previous_error,
                },
                max_tokens=12_000,
                empty_error="DeepSeek returned an empty response",
                invalid_error="DeepSeek did not return valid JSON",
            )
            for key in total_usage:
                total_usage[key] += int(completed["usage"].get(key, 0) or 0)
            payload = completed["payload"]
            try:
                if not isinstance(payload.get("source_code"), str):
                    raise ValueError(
                        "DeepSeek response must contain one source_code string"
                    )
                source_code = payload["source_code"].strip()
                if not source_code:
                    raise ValueError("DeepSeek returned empty source_code")
                change_summary = payload.get("change_summary")
                if (
                    not isinstance(change_summary, list)
                    or not 1 <= len(change_summary) <= 3
                    or not all(
                        isinstance(item, str) and item.strip()
                        for item in change_summary
                    )
                ):
                    raise ValueError(
                        "DeepSeek repair response must contain one to three "
                        "concrete change_summary strings"
                    )
                first_stage = payload.get("first_interrupted_stage")
                if not isinstance(first_stage, str) or not first_stage.strip():
                    raise ValueError(
                        "DeepSeek repair response must contain first_interrupted_stage"
                    )
                if source_code == str(context["source_code"]).strip():
                    raise ValueError(
                        "DeepSeek repair claimed a change but returned unchanged source_code"
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
                if semantic_attempt == 0:
                    continue
                trace = dict(completed["trace"])
                trace["semantic_validation_attempts"] = semantic_attempts
                trace["semantic_retry_count"] = 1
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
                "source_code": source_code,
                "change_summary": change_summary,
                "first_interrupted_stage": first_stage,
                "usage": total_usage,
                "trace": trace,
            }
        raise AssertionError("unreachable Repair semantic retry state")
