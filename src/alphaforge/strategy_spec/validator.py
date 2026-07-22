from __future__ import annotations

from dataclasses import dataclass

from alphaforge.schemas.strategy_spec import StrategySpec


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


_ALLOWED_CHANGE_ROOTS = (
    "/strategy_id",
    "/parent_strategy_id",
    "/candidate_type",
    "/logic",
    "/execution/top_k",
    "/execution/target_gross",
    "/execution/regime_filter",
    "/execution/regime_lookback_days",
)


def validate_strategy_spec(
    spec: StrategySpec,
    *,
    parent: StrategySpec,
    changed_paths: tuple[str, ...],
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if spec.universe != parent.universe:
        issues.append(
            ValidationIssue(
                "UNIVERSE_CHANGE_FORBIDDEN",
                "/universe",
                "candidate cannot change the approved universe",
            )
        )
    if (
        spec.execution.start_date != parent.execution.start_date
        or spec.execution.end_date != parent.execution.end_date
        or spec.execution.initial_cash != parent.execution.initial_cash
        or spec.execution.resolution != parent.execution.resolution
        or spec.execution.rebalance != parent.execution.rebalance
    ):
        issues.append(
            ValidationIssue(
                "EXECUTION_PROTOCOL_CHANGE_FORBIDDEN",
                "/execution",
                "candidate cannot change the comparison protocol",
            )
        )
    if spec.risk != parent.risk:
        issues.append(
            ValidationIssue(
                "RISK_POLICY_CHANGE_FORBIDDEN",
                "/risk",
                "candidate cannot change hard risk policy",
            )
        )
    for path in changed_paths:
        if not any(path == root or path.startswith(root + "/") for root in _ALLOWED_CHANGE_ROOTS):
            issues.append(
                ValidationIssue(
                    "CHANGE_SCOPE_FORBIDDEN",
                    path,
                    "candidate changed a field outside the allowlist",
                )
            )
    ml_logic = spec.logic.ml if spec.logic.kind == "hybrid" else spec.logic
    if ml_logic.kind == "ml" and ml_logic.feature_set_version != "price_volume_v1":
        issues.append(
            ValidationIssue(
                "UNKNOWN_FEATURE_SET",
                "/logic/feature_set_version",
                "qc_semantics_v1 supports only price_volume_v1",
            )
        )
    return tuple(issues)
