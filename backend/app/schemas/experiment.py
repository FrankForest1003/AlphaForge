from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RunSettings(BaseModel):
    """Shared market and execution settings for every strategy in one Forge run."""

    model_config = ConfigDict(extra="forbid")

    symbols: list[str]
    start_date: date
    end_date: date
    initial_cash: float = Field(default=100_000.0, gt=0)
    benchmark: str = Field(default="SPY", min_length=1, max_length=16)
    transaction_cost_bps: float = Field(default=10.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip().upper() for item in value if str(item).strip()]
        if len(normalized) < 5:
            raise ValueError("select at least five stocks")
        if len(normalized) > 30:
            raise ValueError("select no more than thirty stocks")
        if len(normalized) != len(set(normalized)):
            raise ValueError("symbols must be unique")
        return normalized

    @field_validator("benchmark")
    @classmethod
    def normalize_benchmark(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be earlier than end_date")
        return self

    def worker_parameters(self) -> dict[str, str]:
        return {
            "symbols": ",".join(self.symbols),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "initial_cash": str(self.initial_cash),
            "benchmark": self.benchmark,
            "transaction_cost_bps": str(self.transaction_cost_bps),
            "slippage_bps": str(self.slippage_bps),
        }


class GuidedHumanStrategy(BaseModel):
    """Validated controls exposed by the basic and advanced Guided UI."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["basic", "advanced"] = "basic"
    signal: Literal[
        "momentum",
        "mean_reversion",
        "low_volatility",
        "momentum_low_volatility",
        "trend_quality",
    ] = "momentum"
    lookback_days: int = Field(default=60, ge=10, le=252)
    secondary_lookback_days: int = Field(default=63, ge=10, le=252)
    primary_signal_weight: float = Field(default=0.65, ge=0.20, le=0.90)
    rebalance: Literal["weekly", "monthly"] = "monthly"
    holdings: int = Field(default=3, ge=2, le=10)
    weighting: Literal["equal", "inverse_volatility", "score"] = "equal"
    gross_exposure: float = Field(default=0.90, ge=0.50, le=0.95)
    max_position_weight: float = Field(default=0.45, ge=0.10, le=0.60)
    rebalance_threshold: float = Field(default=0.02, ge=0.0, le=0.10)
    require_positive_score: bool = False
    market_trend_filter: bool = False
    market_sma_window: int = Field(default=200, ge=20, le=252)

    @model_validator(mode="after")
    def validate_capacity(self):
        if self.holdings * self.max_position_weight + 1e-12 < self.gross_exposure:
            raise ValueError(
                "holdings * max_position_weight must cover gross_exposure"
            )
        return self


class HumanStrategyRequest(BaseModel):
    """Discriminated Human input without silently mixing code and Guided modes."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["code", "guided"]
    source_code: str | None = None
    guided: GuidedHumanStrategy | None = None

    @model_validator(mode="after")
    def validate_mode_payload(self):
        if self.mode == "code":
            if not isinstance(self.source_code, str) or not self.source_code.strip():
                raise ValueError("source_code is required in code mode")
            if self.guided is not None:
                raise ValueError("guided settings are only valid in guided mode")
        else:
            if self.guided is None:
                raise ValueError("guided settings are required in guided mode")
            if self.source_code not in (None, ""):
                raise ValueError("source_code is only valid in code mode")
        return self


class ForgeRunRequest(BaseModel):
    """API contract for a standalone run or the next round of one battle."""

    model_config = ConfigDict(extra="forbid")

    settings: RunSettings
    human_strategy: HumanStrategyRequest
    battle_id: str | None = Field(default=None, min_length=1, max_length=80)


class RobustnessRunRequest(BaseModel):
    """Select which completed strategy receives the scenario stress suite."""

    model_config = ConfigDict(extra="forbid")

    target: Literal["best_ai", "human"] = "best_ai"
