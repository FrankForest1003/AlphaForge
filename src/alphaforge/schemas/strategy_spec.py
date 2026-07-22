from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CandidateType = Literal["user", "traditional", "ml", "hybrid"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UniverseSpec(StrictModel):
    symbols: tuple[str, ...] = Field(min_length=10, max_length=30)
    whitelist_version: str = "whitelist_v1.0"

    @model_validator(mode="after")
    def symbols_must_be_unique(self) -> "UniverseSpec":
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("universe symbols must be unique")
        return self


class ExecutionSpec(StrictModel):
    start_date: date
    end_date: date
    initial_cash: float = Field(default=100_000, gt=0)
    resolution: Literal["daily"] = "daily"
    rebalance: Literal["monthly"] = "monthly"
    top_k: int = Field(default=3, ge=1, le=10)
    target_gross: float = Field(default=0.95, ge=0.25, le=0.95)
    regime_filter: Literal["none", "benchmark_sma"] = "none"
    regime_lookback_days: int | None = Field(default=None, ge=50, le=300)

    @model_validator(mode="after")
    def period_must_increase(self) -> "ExecutionSpec":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.regime_filter == "none" and self.regime_lookback_days is not None:
            raise ValueError("regime_lookback_days requires benchmark_sma")
        if self.regime_filter == "benchmark_sma" and self.regime_lookback_days is None:
            raise ValueError("benchmark_sma requires regime_lookback_days")
        return self


class RiskConstraints(StrictModel):
    long_only: Literal[True] = True
    max_leverage: Literal[1.0] = 1.0
    max_position_weight: float = Field(default=0.35, gt=0, le=0.35)
    max_drawdown_limit: float = Field(default=0.25, gt=0, le=1)


class TraditionalLogic(StrictModel):
    kind: Literal["traditional"] = "traditional"
    signal: Literal["momentum_rank", "mean_reversion_rank"]
    lookback_days: int = Field(ge=20, le=504)


class MLLogic(StrictModel):
    kind: Literal["ml"] = "ml"
    model: Literal["gradient_boosting", "random_forest"]
    task: Literal["relative_alpha_regression", "direction_classification"]
    training_window_days: int = Field(ge=252, le=2520)
    prediction_horizon_days: int = Field(ge=1, le=63)
    feature_set_version: str
    random_seed: int


class HybridLogic(StrictModel):
    kind: Literal["hybrid"] = "hybrid"
    traditional: TraditionalLogic
    ml: MLLogic
    traditional_weight: float = Field(gt=0, lt=1)


StrategyLogic = Annotated[
    TraditionalLogic | MLLogic | HybridLogic,
    Field(discriminator="kind"),
]


class StrategySpec(StrictModel):
    """Canonical strategy semantics used by every downstream component."""

    schema_version: Literal["1.0"] = "1.0"
    strategy_id: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    parent_strategy_id: str | None = None
    candidate_type: CandidateType
    universe: UniverseSpec
    execution: ExecutionSpec
    risk: RiskConstraints
    logic: StrategyLogic

    @model_validator(mode="after")
    def route_must_match_logic(self) -> "StrategySpec":
        expected = "traditional" if self.candidate_type == "user" else self.candidate_type
        if self.logic.kind != expected:
            raise ValueError(
                f"candidate_type={self.candidate_type!r} requires logic.kind={expected!r}"
            )
        if self.candidate_type != "user" and not self.parent_strategy_id:
            raise ValueError("candidate strategies require parent_strategy_id")
        return self
