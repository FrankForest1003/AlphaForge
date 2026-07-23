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
        if not normalized:
            raise ValueError("select at least one stock")
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
    model_config = ConfigDict(extra="forbid")

    signal: Literal["momentum", "mean_reversion"] = "momentum"
    lookback_days: Literal[20, 60, 120] = 60
    rebalance: Literal["weekly", "monthly"] = "monthly"
    holdings: int = Field(default=2, ge=1, le=3)


class HumanStrategyRequest(BaseModel):
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
    model_config = ConfigDict(extra="forbid")

    settings: RunSettings
    human_strategy: HumanStrategyRequest
