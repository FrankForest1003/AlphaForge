from __future__ import annotations

from typing import Literal

from pydantic import Field

from alphaforge.schemas.manifests import LeanEnvironmentManifest, StrategyManifest
from alphaforge.schemas.strategy_spec import StrictModel
from alphaforge.schemas.strategy_spec import StrategySpec


class BacktestMetrics(StrictModel):
    cagr: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float = Field(ge=0, le=1)
    annual_volatility: float = Field(ge=0)
    turnover: float = Field(ge=0)
    total_fees: float = Field(ge=0)


class BacktestResult(StrictModel):
    run_id: str
    strategy_id: str
    strategy_role: Literal["user", "baseline_b1", "baseline_b2", "baseline_b3", "baseline_b4", "candidate"]
    status: Literal["completed", "failed"]
    dataset_split: Literal["train", "validation", "test"]
    provider: str
    metrics: BacktestMetrics | None = None
    warnings: tuple[str, ...] = ()


class SmokeTestResult(StrictModel):
    strategy_id: str
    status: Literal["passed", "failed"]
    diagnostics: tuple[str, ...] = ()
    provider: str


class BacktestSubmission(StrictModel):
    """Transport-safe request; code artefacts are referenced, never embedded paths."""

    strategy_manifest: StrategyManifest
    environment_manifest: LeanEnvironmentManifest
    strategy_spec: StrategySpec
    code_artifact_id: str
