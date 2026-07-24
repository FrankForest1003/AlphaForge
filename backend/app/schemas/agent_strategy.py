from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.strategy_template import StrategyTemplateSpec


class DesignRationale(BaseModel):
    """Small, user-facing explanation attached to a parameter proposal."""

    model_config = ConfigDict(extra="forbid")

    reference_baselines: list[str] = Field(min_length=1, max_length=2)
    improvement_hypothesis: str = Field(min_length=10, max_length=500)
    differentiation: list[str] = Field(min_length=1, max_length=3)
    expected_tradeoff: str = Field(min_length=10, max_length=500)


class CandidateProposal(BaseModel):
    """The complete output of Designer: explanation plus template parameters."""

    model_config = ConfigDict(extra="forbid")

    design: DesignRationale
    strategy_spec: StrategyTemplateSpec


class ParameterSuggestion(BaseModel):
    """One bounded direction for Designer; Critic never edits the spec itself."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=2, max_length=120)
    direction: Literal["increase", "decrease", "replace", "enable", "disable", "keep"]
    reason: str = Field(min_length=8, max_length=400)


class CritiqueReport(BaseModel):
    """Performance review returned after one completed template backtest."""

    model_config = ConfigDict(extra="forbid")

    iteration: int = Field(ge=1, le=3)
    diagnosis: str = Field(min_length=10, max_length=700)
    strengths: list[str] = Field(default_factory=list, max_length=4)
    weaknesses: list[str] = Field(default_factory=list, max_length=4)
    preserve: list[str] = Field(default_factory=list, max_length=3)
    recommended_changes: list[ParameterSuggestion] = Field(
        default_factory=list,
        max_length=3,
    )
    overfitting_warning: str = Field(min_length=8, max_length=400)

    @model_validator(mode="after")
    def require_actionable_review(self):
        if not self.strengths and not self.weaknesses:
            raise ValueError("Critic must report at least one strength or weakness")
        return self


def compact_iteration_result(
    *,
    iteration: int,
    summary: dict[str, Any],
    analysis: dict[str, Any],
    behavior_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Keep Agent context focused on comparable metrics and execution facts."""

    statistics = analysis.get("statistics", {}) if isinstance(analysis, dict) else {}
    return {
        "iteration": iteration,
        "summary": {
            key: summary.get(key)
            for key in (
                "cagr",
                "sharpe_ratio",
                "maximum_drawdown",
                "end_equity",
            )
        },
        "statistics": {
            key: statistics.get(key)
            for key in (
                "annualized_volatility",
                "annualized_turnover",
                "total_fees",
            )
        },
        "execution": {
            key: behavior_evidence.get(key)
            for key in (
                "filled_order_count",
                "invested_snapshot_count",
                "max_gross_exposure",
                "rebalance_completed_count",
                "signal_event_count",
                "ml_training_run_count",
                "ml_prediction_count",
                "signal_target_link_count",
                "prediction_target_link_count",
                "hybrid_decision_link_count",
            )
        },
    }
