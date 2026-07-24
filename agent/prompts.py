from __future__ import annotations


DESIGNER_TRACKS = ("Traditional", "ML", "Hybrid")

TRACK_BRIEFS = {
    "Traditional": (
        "Use one to four transparent price/volume features. No model is allowed; "
        "the signal blend must directly determine rank and portfolio targets."
    ),
    "ML": (
        "Use two to twelve lagged features and one supported sklearn model. "
        "Model predictions must directly determine rank and portfolio targets."
    ),
    "Hybrid": (
        "Combine a transparent signal blend and fitted-model prediction in the "
        "same final rank and portfolio decision."
    ),
}

DESIGNER_SYSTEM_PROMPT = """You are the AlphaForge Parameter Designer.
Return one JSON object containing `design` and `strategy_spec`; never return Python,
pseudocode, markdown, or additional keys. The backend owns a tested LEAN template and
will reject parameters outside the supplied DSL, so focus on an auditable investment
hypothesis. Use only public baseline results and prior AI iterations. Change a small
number of parameters per revision, preserve observed strengths, and do not promise
outperformance. A revision must differ materially from the previous complete spec."""

CRITIC_SYSTEM_PROMPT = """You are the AlphaForge Performance Critic.
Evaluate one completed parameterized-strategy backtest against its public references
and its earlier iterations. Return one JSON object matching the requested critique
shape. Do not return code, a replacement strategy_spec, acceptance/rejection, or claims
of future performance. Identify what to preserve and recommend at most three bounded
parameter directions for the Designer. Prefer interpretable changes and explicitly
warn about multiple-testing and overfitting risk."""

STRATEGY_DSL = {
    "schema_version": "template-v1",
    "strategy_name": "3-80 characters",
    "track": "Traditional | ML | Hybrid; must equal assigned track",
    "thesis": "10-500 characters",
    "signal": {
        "rule": "required Traditional/Hybrid; null ML",
        "components": "1-4 unique components",
        "feature.kind": (
            "return | volatility | sma_gap | relative_return | "
            "volume_change | rsi"
        ),
        "feature.window": "integer 2-252",
        "direction": "higher | lower",
        "weight": "number >0 and <=1",
    },
    "model": {
        "rule": "null Traditional; required ML/Hybrid",
        "algorithm": "gradient_boosting | random_forest | extra_trees | ridge",
        "features": "2-12 unique feature objects using the feature catalog",
        "target": "absolute_return | excess_return",
        "horizon_days": "integer 5-63",
        "pooled_training_rows": "integer 80-600",
        "retrain_every_rebalances": "integer 1-6",
        "n_estimators": "integer 40-400",
        "learning_rate": "number 0.01-0.30",
        "max_depth": "integer 1-8",
        "min_samples_leaf": "integer 2-100",
        "ridge_alpha": "number 0.01-100",
    },
    "selection": {
        "top_k": "integer 2-10 and <= number of run symbols",
        "require_positive_score": "boolean",
        "hybrid_model_weight": "number 0.10-0.90",
    },
    "portfolio": {
        "weighting": (
            "equal | inverse_volatility | score | minimum_variance | "
            "blend_score_minimum_variance"
        ),
        "gross_exposure": "number 0.50-0.98",
        "max_position_weight": "number 0.10-0.60",
        "constraint": "top_k * max_position_weight >= gross_exposure",
        "volatility_window": "integer 10-252",
        "minimum_variance_blend": "number 0-1",
        "rebalance_threshold": "number 0-0.10",
    },
    "schedule": {
        "frequency": "weekly | monthly",
        "minutes_after_open": "integer 5-120",
    },
    "risk": {
        "market_trend_filter": "boolean",
        "market_sma_window": "integer 20-252",
        "stop_loss": "null or number 0.05-0.30",
        "maximum_drawdown": "null or number 0.10-0.40",
        "cooldown_days": "integer 5-90",
    },
}

PROPOSAL_SHAPE = {
    "design": {
        "reference_baselines": ["one or two exact public baseline names"],
        "improvement_hypothesis": "one falsifiable hypothesis",
        "differentiation": ["one to three concrete parameter differences"],
        "expected_tradeoff": "what may improve and what may worsen",
    },
    "strategy_spec": "one complete object matching STRATEGY_DSL",
}

CRITIQUE_SHAPE = {
    "iteration": "integer 1-3",
    "diagnosis": "evidence-based performance diagnosis",
    "strengths": ["zero to four observed strengths"],
    "weaknesses": ["zero to four observed weaknesses"],
    "preserve": ["zero to three mechanisms or parameters to retain"],
    "recommended_changes": [
        {
            "field": "dot path inside strategy_spec",
            "direction": "increase | decrease | replace | enable | disable | keep",
            "reason": "metric- or behavior-based reason",
        }
    ],
    "overfitting_warning": "specific caution for this iteration",
}
