from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from alphaforge.schemas.strategy_spec import StrictModel


class StrategyManifest(StrictModel):
    strategy_id: str
    strategy_family: Literal["user", "traditional", "ml", "hybrid", "benchmark"]
    entry_file: str
    spec_file: str
    resolution: Literal["daily"] = "daily"
    symbols_source: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    data_requirements: tuple[str, ...] = ()
    python_dependencies: tuple[str, ...] = ()
    random_seed: int | None = None


class LeanEnvironmentManifest(StrictModel):
    provider: Literal["local_lean", "quantconnect_cloud", "mock"]
    lean_version: str
    python_version: str
    data_version: str
    normalization_mode: Literal["adjusted"] = "adjusted"
    brokerage_model: str
    fee_model: str
    slippage_model: str
    time_zone: str
