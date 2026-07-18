from __future__ import annotations

from dataclasses import dataclass

from alphaforge.schemas.agent_outputs import CandidateProposal
from alphaforge.schemas.strategy_spec import StrategySpec


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


_ALLOWED_CHANGE_ROOTS = (
    "/candidate_type",
    "/logic",
    "/execution/top_k",
    "/risk/max_position_weight",
    "/risk/max_drawdown_limit",
)


def validate_strategy_spec(
    spec: StrategySpec,
    *,
    parent: StrategySpec | None = None,
    proposal: CandidateProposal | None = None,
) -> tuple[ValidationIssue, ...]:
    """Deterministic cross-field and mutation-scope checks after Pydantic validation."""

    issues: list[ValidationIssue] = []

    if spec.execution.top_k * spec.risk.max_position_weight < 0.99:
        issues.append(
            ValidationIssue(
                "INSUFFICIENT_CAPACITY",
                "/risk/max_position_weight",
                "top_k × max_position_weight cannot deploy approximately all capital",
            )
        )

    if parent is not None:
        if spec.universe != parent.universe:
            issues.append(
                ValidationIssue(
                    "UNIVERSE_CHANGE_FORBIDDEN",
                    "/universe",
                    "Agent candidates cannot change the approved universe in Phase 1",
                )
            )
        if (
            spec.execution.start_date != parent.execution.start_date
            or spec.execution.end_date != parent.execution.end_date
        ):
            issues.append(
                ValidationIssue(
                    "PERIOD_CHANGE_FORBIDDEN",
                    "/execution",
                    "Agent candidates cannot change the comparison period",
                )
            )

    if proposal is not None:
        for path in proposal.changed_paths:
            if not any(path == root or path.startswith(root + "/") for root in _ALLOWED_CHANGE_ROOTS):
                issues.append(
                    ValidationIssue(
                        "CHANGE_SCOPE_FORBIDDEN",
                        path,
                        "Agent declared a change outside the Phase 1 allowlist",
                    )
                )

    return tuple(issues)
