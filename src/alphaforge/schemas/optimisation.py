from __future__ import annotations

from pydantic import Field

from alphaforge.schemas.backtest import BacktestResult
from alphaforge.schemas.strategy_spec import StrategySpec, StrictModel


class OptimizationConstraints(StrictModel):
    max_rounds: int = Field(default=1, ge=1, le=2)
    min_sharpe_improvement: float = Field(default=0.05, ge=0)
    max_drawdown_deterioration: float = Field(default=0.02, ge=0, le=1)


class OptimizationRequest(StrictModel):
    optimization_id: str
    parent_spec: StrategySpec
    evidence: tuple[BacktestResult, ...] = Field(min_length=5, max_length=5)
    constraints: OptimizationConstraints = OptimizationConstraints()
