from __future__ import annotations

from typing import Any


ACCEPTANCE_CHECK_IDS = ("A1", "A2", "A3", "A4", "A5")
POLICY_VERSION = "deterministic-acceptance-v2"
TIME_INTEGRITY_DIAGNOSTICS = {
    "ML_FORWARD_LABEL_FILL",
}


def normalize_acceptance_payload(payload: Any) -> dict[str, Any]:
    """Unwrap provider-specific JSON envelopes without trusting their verdict."""

    if not isinstance(payload, dict):
        return {}
    current = payload
    for _ in range(3):
        if any(key in current for key in ("decision", "checks", "repair_request")):
            return current
        nested = next(
            (
                current.get(key)
                for key in ("output", "report", "result")
                if isinstance(current.get(key), dict)
            ),
            None,
        )
        if nested is None:
            break
        current = nested
    return current


def _diagnostic_codes(preflight_report: dict[str, Any] | None) -> set[str]:
    report = preflight_report or {}
    return {
        str(item.get("code"))
        for item in report.get("diagnostics", [])
        if isinstance(item, dict) and item.get("code")
    }


def _check(
    check_id: str,
    passed: bool,
    evidence: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "evidence": evidence,
        "reason": reason,
    }


def _first_missing_stage(
    track: str,
    evidence: dict[str, Any],
) -> tuple[str | None, list[tuple[str, int]]]:
    stages: list[tuple[str, int]] = []
    if track in {"ML", "Hybrid"}:
        stages.extend(
            [
                ("recorded model training", int(evidence.get("ml_training_run_count") or 0)),
                ("recorded model predictions", int(evidence.get("ml_prediction_count") or 0)),
            ]
        )
    if track in {"Traditional", "Hybrid"}:
        stages.append(
            (
                "recorded transparent signal",
                int(
                    evidence.get(
                        "transparent_signal_event_count",
                        evidence.get("signal_event_count"),
                    )
                    or 0
                ),
            )
        )
    if track == "ML":
        stages.append(
            (
                "prediction-to-target decision link",
                int(evidence.get("prediction_to_target_link_count") or 0),
            )
        )
    elif track == "Traditional":
        stages.append(
            (
                "signal-to-target decision link",
                int(evidence.get("signal_to_target_link_count") or 0),
            )
        )
    else:
        stages.append(
            (
                "hybrid signal-and-prediction target link",
                int(evidence.get("hybrid_decision_link_count") or 0),
            )
        )
    stages.append(
        (
            "non-zero target intent",
            int(
                evidence.get(
                    "target_intent_event_count",
                    evidence.get("nonzero_target_event_count"),
                )
                or 0
            ),
        )
    )
    # Evidence produced before schema 2.0 remains replayable. New Worker details
    # always expose this counter, so a present zero is a deterministic failure.
    if "staged_rebalance_completed_count" in evidence:
        stages.append(
            (
                "completed staged rebalance",
                int(evidence.get("staged_rebalance_completed_count") or 0),
            )
        )
    stages.append(("filled orders", int(evidence.get("filled_order_count") or 0)))
    first_missing = next((name for name, count in stages if count <= 0), None)
    return first_missing, stages


def _advisory_repair(payload: dict[str, Any]) -> str | None:
    value = payload.get("repair_request")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def build_deterministic_acceptance_report(
    *,
    track: str,
    run_settings: dict[str, Any],
    worker_result: dict[str, Any],
    behavior_evidence: dict[str, Any],
    preflight_report: dict[str, Any] | None,
    advisory_payload: Any,
) -> dict[str, Any]:
    """Compute the authoritative verdict from typed source/runtime evidence.

    The Agent response is advisory only. It may add a repair suggestion, but it
    cannot change pass/fail statuses or the final decision.
    """

    advisory = normalize_acceptance_payload(advisory_payload)
    diagnostic_codes = _diagnostic_codes(preflight_report)

    fills = int(behavior_evidence.get("filled_order_count") or 0)
    invested = int(behavior_evidence.get("invested_snapshot_count") or 0)
    gross = float(behavior_evidence.get("max_gross_exposure") or 0)
    a1_pass = fills > 0 and invested > 0 and gross > 0
    a1 = _check(
        "A1",
        a1_pass,
        [
            f"filled_order_count={fills}",
            f"invested_snapshot_count={invested}",
            f"max_gross_exposure={gross:.6f}",
        ],
        (
            "Runtime evidence proves actual investment activity."
            if a1_pass
            else "Actual investment activity requires positive fills, invested snapshots, and gross exposure."
        ),
    )

    first_missing, causal_stages = _first_missing_stage(track, behavior_evidence)
    completed = worker_result.get("status") == "completed"
    a2_pass = completed and first_missing is None
    a2 = _check(
        "A2",
        a2_pass,
        [
            f"worker_status={worker_result.get('status')}",
            *[f"{name}={count}" for name, count in causal_stages],
            "staged_rebalance_replacement_count="
            + str(
                int(
                    behavior_evidence.get(
                        "staged_rebalance_replacement_count"
                    )
                    or 0
                )
            ),
            "staged_rebalance_failed_count="
            + str(
                int(
                    behavior_evidence.get("staged_rebalance_failed_count")
                    or 0
                )
            ),
        ],
        (
            "The deterministic runtime chain reaches a completed staged rebalance and filled orders."
            if a2_pass
            else f"The first missing causal stage is: {first_missing or 'completed worker execution'}."
        ),
    )

    training = int(behavior_evidence.get("ml_training_run_count") or 0)
    predictions = int(behavior_evidence.get("ml_prediction_count") or 0)
    transparent = int(
        behavior_evidence.get(
            "transparent_signal_event_count",
            behavior_evidence.get("signal_event_count"),
        )
        or 0
    )
    if track == "Traditional":
        link_count = int(behavior_evidence.get("signal_to_target_link_count") or 0)
        a3_pass = transparent > 0 and link_count > 0 and training == 0 and predictions == 0
        a3_evidence = [
            f"transparent_signal_event_count={transparent}",
            f"signal_to_target_link_count={link_count}",
            f"ml_training_run_count={training}",
            f"ml_prediction_count={predictions}",
        ]
    elif track == "ML":
        link_count = int(behavior_evidence.get("prediction_to_target_link_count") or 0)
        a3_pass = training > 0 and predictions > 0 and link_count > 0
        a3_evidence = [
            f"ml_training_run_count={training}",
            f"ml_prediction_count={predictions}",
            f"prediction_to_target_link_count={link_count}",
        ]
    else:
        link_count = int(behavior_evidence.get("hybrid_decision_link_count") or 0)
        a3_pass = (
            training > 0
            and predictions > 0
            and transparent > 0
            and link_count > 0
        )
        a3_evidence = [
            f"ml_training_run_count={training}",
            f"ml_prediction_count={predictions}",
            f"transparent_signal_event_count={transparent}",
            f"hybrid_decision_link_count={link_count}",
        ]
    a3 = _check(
        "A3",
        a3_pass,
        a3_evidence,
        (
            f"Recorded evidence satisfies the {track} track contract."
            if a3_pass
            else f"Recorded evidence does not satisfy the {track} track contract."
        ),
    )

    time_diagnostics = sorted(diagnostic_codes.intersection(TIME_INTEGRITY_DIAGNOSTICS))
    if track == "Traditional":
        ordered_events = int(behavior_evidence.get("signal_to_target_link_count") or 0)
    else:
        ordered_events = int(
            behavior_evidence.get("training_before_prediction_count") or 0
        )
    a4_pass = not time_diagnostics and ordered_events > 0
    a4 = _check(
        "A4",
        a4_pass,
        [
            "time_integrity_diagnostics="
            + (",".join(time_diagnostics) if time_diagnostics else "none"),
            f"ordered_runtime_evidence_count={ordered_events}",
        ],
        (
            "The bounded source contract and ordered runtime events contain no detected time-integrity violation."
            if a4_pass
            else "Time integrity is not established by both static and ordered runtime evidence."
        ),
    )

    allowed_symbols = {
        str(symbol).strip().upper()
        for symbol in run_settings.get("symbols", [])
        if str(symbol).strip()
    }
    traded_symbols = {
        str(symbol).strip().upper()
        for symbol in behavior_evidence.get("traded_symbols", [])
        if str(symbol).strip()
    }
    unauthorized = sorted(traded_symbols - allowed_symbols)
    settings_missing = "MISSING_RUN_SETTINGS" in diagnostic_codes
    benchmark = str(run_settings.get("benchmark") or "").strip().upper()
    benchmark_traded = bool(benchmark and benchmark in traded_symbols and benchmark not in allowed_symbols)
    a5_pass = not settings_missing and not unauthorized and not benchmark_traded
    a5 = _check(
        "A5",
        a5_pass,
        [
            f"consumed_run_settings={'no' if settings_missing else 'yes'}",
            f"unauthorized_traded_symbols={unauthorized}",
            f"benchmark_traded_as_candidate={str(benchmark_traded).lower()}",
        ],
        (
            "Shared settings and the permitted stock universe are respected."
            if a5_pass
            else "The source/settings mapping or permitted stock universe was violated."
        ),
    )

    checks = [a1, a2, a3, a4, a5]
    failed = [item["id"] for item in checks if item["status"] == "fail"]
    decision = "accept" if not failed else "revise"
    repair_request = None
    agent_advisory_repair_request = _advisory_repair(advisory)
    if failed:
        repair_request = (
            f"Deterministic policy failed {', '.join(failed)}. "
            f"First interrupted stage: {first_missing or failed[0]}."
        )

    return {
        "decision": decision,
        "checks": checks,
        "repair_request": repair_request,
        "agent_advisory_repair_request": agent_advisory_repair_request,
        "policy_version": POLICY_VERSION,
        "decision_source": "backend_deterministic_policy",
        "agent_advisory_decision": advisory.get("decision"),
    }
