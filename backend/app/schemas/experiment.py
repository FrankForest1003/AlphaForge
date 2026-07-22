from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExperimentContract(BaseModel):
    """Immutable rules shared by Human, public baselines, and AI candidates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1.0"] = "1.0"
    universe_id: str = "alphaforge_us_equity_30_v1.0"
    universe_version: str = "whitelist_v1.0"
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    initial_cash: float = Field(default=100_000.0, gt=0)
    resolution: Literal["Daily"] = "Daily"
    rebalance_frequency: Literal["Monthly"] = "Monthly"
    top_k: int = Field(default=3, ge=1, le=10)
    target_gross: float = Field(default=0.95, gt=0, le=1)
    max_position_weight: float = Field(default=0.35, gt=0, le=1)
    max_drawdown: float = Field(default=0.25, gt=0, lt=1)
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=100)
    slippage_bps: float = Field(default=5.0, ge=0, le=100)
    long_only: Literal[True] = True
    max_leverage: Literal[1.0] = 1.0
    cash_allowed: Literal[True] = True
    benchmark: Literal["SPY"] = "SPY"
    risk_filter_symbol: Literal["QQQ"] = "QQQ"
    risk_sma_period: int = Field(default=200, ge=20, le=500)
    data_version: str = Field(min_length=1, max_length=100)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(item).strip().upper() for item in value if str(item).strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("symbols must be unique")
        if not 5 <= len(normalized) <= 30:
            raise ValueError("symbols must contain 5 to 30 whitelist stocks")
        return normalized

    @model_validator(mode="after")
    def validate_dates_and_weights(self):
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be earlier than end_date")
        if self.top_k > len(self.symbols):
            raise ValueError("top_k cannot exceed the selected universe size")
        if self.max_position_weight * self.top_k < self.target_gross - 1e-12:
            raise ValueError("top_k and max_position_weight cannot reach target_gross")
        return self

    def canonical_payload(self) -> dict:
        return self.model_dump(mode="json")

    def sha256(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class BattleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="AlphaForge Battle", min_length=1, max_length=120)
    experiment_contract: ExperimentContract


class BattleView(BaseModel):
    battle_id: str
    name: str
    status: str
    contract_hash: str
    experiment_contract: ExperimentContract
    created_at: str
