from __future__ import annotations

from typing import Any


POLICY_VERSION = "independent-acceptance-agent-v3"


def normalize_acceptance_payload(payload: Any) -> dict[str, Any]:
    """Unwrap common provider JSON envelopes before coherence validation.

    This function does not create or replace A2-A4 judgments. The independent
    Acceptance Agent remains the source of those statuses and the final semantic
    decision.
    """

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
