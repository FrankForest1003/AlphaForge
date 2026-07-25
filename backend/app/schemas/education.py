from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrategyExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thesis: str = Field(min_length=20, max_length=500)
    mechanics: list[str] = Field(min_length=3, max_length=6)
    why_it_led: list[str] = Field(min_length=2, max_length=5)
    failure_modes: list[str] = Field(min_length=2, max_length=5)


class NextRoundAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=5, max_length=100)
    hypothesis: str = Field(min_length=15, max_length=400)
    parameter_path: str = Field(min_length=3, max_length=120)
    current_value: str = Field(min_length=1, max_length=100)
    proposed_value: str = Field(min_length=1, max_length=100)
    expected_metric: Literal[
        "CAGR",
        "Sharpe Ratio",
        "Maximum Drawdown",
        "Turnover",
        "Robustness",
    ]
    tradeoff: str = Field(min_length=10, max_length=300)
    validation: str = Field(min_length=15, max_length=400)


class QuantConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=5, max_length=100)
    explanation: str = Field(min_length=30, max_length=700)
    chart_hint: Literal[
        "risk_return",
        "drawdown_path",
        "turnover_cost",
        "iteration_stability",
        "diversification",
    ]
    takeaway: str = Field(min_length=15, max_length=300)


class EducationReview(BaseModel):
    """Grounded user-facing explanation; it never decides the winner."""

    model_config = ConfigDict(extra="forbid")

    strategy_explanation: StrategyExplanation
    next_round_actions: list[NextRoundAction] = Field(min_length=2, max_length=3)
    quant_concept: QuantConcept
    overfitting_watch: list[str] = Field(min_length=2, max_length=4)
