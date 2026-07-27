from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Track = Literal["Traditional", "ML", "Hybrid"]
FeatureKind = Literal[
    "return",
    "volatility",
    "sma_gap",
    "relative_return",
    "volume_change",
    "rsi",
]


class FeatureSpec(BaseModel):
    """One deterministic feature implemented by the versioned LEAN template."""

    model_config = ConfigDict(extra="forbid")

    kind: FeatureKind
    window: int = Field(ge=2, le=252)

    @property
    def key(self) -> str:
        return f"{self.kind}_{self.window}"


class SignalComponentSpec(BaseModel):
    """A transparent feature direction used in a cross-sectional rank."""

    model_config = ConfigDict(extra="forbid")

    feature: FeatureSpec
    direction: Literal["higher", "lower"] = "higher"
    weight: float = Field(default=1.0, gt=0, le=1)


class SignalBlendSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    components: list[SignalComponentSpec] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_components(self):
        identities = [
            (component.feature.key, component.direction)
            for component in self.components
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("signal components must be unique")
        return self


class ModelSpec(BaseModel):
    """A bounded sklearn model whose data pipeline remains template-owned."""

    model_config = ConfigDict(extra="forbid")

    algorithm: Literal[
        "gradient_boosting",
        "random_forest",
        "extra_trees",
        "ridge",
    ] = "gradient_boosting"
    features: list[FeatureSpec] = Field(min_length=2, max_length=12)
    target: Literal["absolute_return", "excess_return"] = "excess_return"
    horizon_days: int = Field(default=21, ge=5, le=63)
    pooled_training_rows: int = Field(default=360, ge=80, le=600)
    retrain_every_rebalances: int = Field(default=1, ge=1, le=6)
    n_estimators: int = Field(default=120, ge=40, le=400)
    learning_rate: float = Field(default=0.05, ge=0.01, le=0.30)
    max_depth: int = Field(default=2, ge=1, le=8)
    min_samples_leaf: int = Field(default=12, ge=2, le=100)
    ridge_alpha: float = Field(default=1.0, ge=0.01, le=100.0)

    @model_validator(mode="after")
    def unique_features(self):
        keys = [feature.key for feature in self.features]
        if len(keys) != len(set(keys)):
            raise ValueError("model features must be unique")
        return self


class SelectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=3, ge=2, le=10)
    require_positive_score: bool = False
    hybrid_model_weight: float = Field(default=0.50, ge=0.10, le=0.90)


class PortfolioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weighting: Literal[
        "equal",
        "inverse_volatility",
        "score",
        "minimum_variance",
        "blend_score_minimum_variance",
    ] = "inverse_volatility"
    gross_exposure: float = Field(default=0.95, ge=0.50, le=0.98)
    max_position_weight: float = Field(default=0.35, ge=0.10, le=0.60)
    volatility_window: int = Field(default=63, ge=10, le=252)
    minimum_variance_blend: float = Field(default=0.35, ge=0.0, le=1.0)
    rebalance_threshold: float = Field(default=0.02, ge=0.0, le=0.10)


class ScheduleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: Literal["weekly", "monthly"] = "monthly"
    minutes_after_open: int = Field(default=30, ge=5, le=120)


class RiskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_trend_filter: bool = True
    market_sma_window: int = Field(default=200, ge=20, le=252)
    stop_loss: float | None = Field(default=None, ge=0.05, le=0.30)
    maximum_drawdown: float | None = Field(default=None, ge=0.10, le=0.40)
    cooldown_days: int = Field(default=21, ge=5, le=90)


class StrategyTemplateSpec(BaseModel):
    """Agent-facing DSL for the fixed AlphaForge strategy template.

    The model intentionally describes strategy decisions rather than Python syntax.
    Shared symbols, dates, cash, benchmark, fees, and slippage remain owned by the
    experiment contract and cannot be changed by an Agent.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["template-v1"] = "template-v1"
    strategy_name: str = Field(min_length=3, max_length=80)
    track: Track
    thesis: str = Field(min_length=10, max_length=500)
    signal: SignalBlendSpec | None = None
    model: ModelSpec | None = None
    selection: SelectionSpec = Field(default_factory=SelectionSpec)
    portfolio: PortfolioSpec = Field(default_factory=PortfolioSpec)
    schedule: ScheduleSpec = Field(default_factory=ScheduleSpec)
    risk: RiskSpec = Field(default_factory=RiskSpec)

    @model_validator(mode="after")
    def validate_track_contract(self):
        if self.track == "Traditional":
            if self.signal is None or self.model is not None:
                raise ValueError(
                    "Traditional requires a transparent signal and no ML model"
                )
        elif self.track == "ML":
            if self.signal is not None or self.model is None:
                raise ValueError("ML requires a model and no transparent signal blend")
        elif self.signal is None or self.model is None:
            raise ValueError("Hybrid requires both a transparent signal and an ML model")
        return self
