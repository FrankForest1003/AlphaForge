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
outperformance. A revision must differ materially from the previous complete spec.
Copy the nesting of `valid_strategy_spec_example` exactly. Never turn documentation
paths into JSON keys: `feature.kind` means `{"feature":{"kind":...}}`, never a key named
`feature.kind`. Never output documentation-only keys such as `rule`, `constraint`, or
`instructions`. Omit irrelevant fields instead of filling them with null. Null is
allowed only where the example or parameter rules explicitly permit it."""

CRITIC_SYSTEM_PROMPT = """You are the AlphaForge Performance Critic.
Evaluate one completed parameterized-strategy backtest against its public references
and its earlier iterations. Return one JSON object matching the requested critique
shape. Do not return code, a replacement strategy_spec, acceptance/rejection, or claims
of future performance. Identify what to preserve and recommend at most three bounded
parameter directions for the Designer. Prefer interpretable changes and explicitly
warn about multiple-testing and overfitting risk."""

PARAMETER_RULES = [
    "Return exactly the keys shown by the assigned track example; no dotted keys.",
    "Traditional: signal is required and model must be null.",
    "ML: signal must be null and model is required.",
    "Hybrid: both signal and model are required.",
    (
        "Feature objects contain exactly kind and window. kind is return, volatility, "
        "sma_gap, relative_return, volume_change, or rsi; window is integer 2-252."
    ),
    "Signal components contain exactly feature, direction, and weight; use 1-4.",
    (
        "Model algorithm is gradient_boosting, random_forest, extra_trees, or ridge; "
        "use 2-12 unique feature objects and horizon_days 5-63."
    ),
    "selection.top_k is 2-10 and cannot exceed the number of run symbols.",
    "selection.hybrid_model_weight is always a number 0.10-0.90, never null.",
    (
        "portfolio.weighting is equal, inverse_volatility, score, minimum_variance, "
        "or blend_score_minimum_variance."
    ),
    (
        "portfolio fields are numeric; minimum_variance_blend is always 0-1, never "
        "null. Ensure top_k * max_position_weight >= gross_exposure."
    ),
    (
        "risk.market_sma_window is always integer 20-252 even when "
        "market_trend_filter is false."
    ),
    "Only risk.stop_loss and risk.maximum_drawdown may be null.",
]

TRACK_SPEC_EXAMPLES = {
    "Traditional": {
        "schema_version": "template-v1",
        "strategy_name": "Transparent Dual Rank",
        "track": "Traditional",
        "thesis": "A transparent return and volatility rank may improve stability.",
        "signal": {
            "components": [
                {
                    "feature": {"kind": "return", "window": 126},
                    "direction": "higher",
                    "weight": 0.7,
                },
                {
                    "feature": {"kind": "volatility", "window": 42},
                    "direction": "lower",
                    "weight": 0.3,
                },
            ]
        },
        "model": None,
        "selection": {
            "top_k": 3,
            "require_positive_score": False,
            "hybrid_model_weight": 0.5,
        },
        "portfolio": {
            "weighting": "inverse_volatility",
            "gross_exposure": 0.9,
            "max_position_weight": 0.35,
            "volatility_window": 63,
            "minimum_variance_blend": 0.35,
            "rebalance_threshold": 0.02,
        },
        "schedule": {"frequency": "monthly", "minutes_after_open": 30},
        "risk": {
            "market_trend_filter": True,
            "market_sma_window": 200,
            "stop_loss": None,
            "maximum_drawdown": None,
            "cooldown_days": 21,
        },
    },
    "ML": {
        "schema_version": "template-v1",
        "strategy_name": "Pooled Ridge Rank",
        "track": "ML",
        "thesis": "A regularized pooled model may produce stable relative rankings.",
        "signal": None,
        "model": {
            "algorithm": "ridge",
            "features": [
                {"kind": "return", "window": 21},
                {"kind": "volatility", "window": 42},
                {"kind": "relative_return", "window": 63},
            ],
            "target": "excess_return",
            "horizon_days": 21,
            "pooled_training_rows": 360,
            "retrain_every_rebalances": 1,
            "n_estimators": 120,
            "learning_rate": 0.05,
            "max_depth": 2,
            "min_samples_leaf": 12,
            "ridge_alpha": 1.0,
        },
        "selection": {
            "top_k": 3,
            "require_positive_score": False,
            "hybrid_model_weight": 0.5,
        },
        "portfolio": {
            "weighting": "inverse_volatility",
            "gross_exposure": 0.9,
            "max_position_weight": 0.35,
            "volatility_window": 63,
            "minimum_variance_blend": 0.35,
            "rebalance_threshold": 0.02,
        },
        "schedule": {"frequency": "monthly", "minutes_after_open": 30},
        "risk": {
            "market_trend_filter": True,
            "market_sma_window": 200,
            "stop_loss": None,
            "maximum_drawdown": None,
            "cooldown_days": 21,
        },
    },
}

TRACK_SPEC_EXAMPLES["Hybrid"] = {
    **TRACK_SPEC_EXAMPLES["ML"],
    "strategy_name": "Hybrid Forecast Momentum",
    "track": "Hybrid",
    "thesis": "Model forecasts and transparent momentum may complement each other.",
    "signal": {
        "components": [
            {
                "feature": {"kind": "return", "window": 126},
                "direction": "higher",
                "weight": 1.0,
            }
        ]
    },
    "selection": {
        **TRACK_SPEC_EXAMPLES["ML"]["selection"],
        "hybrid_model_weight": 0.55,
    },
}

PROPOSAL_SHAPE = {
    "design": {
        "reference_baselines": ["one or two exact public baseline names"],
        "improvement_hypothesis": "one falsifiable hypothesis",
        "differentiation": ["one to three concrete parameter differences"],
        "expected_tradeoff": "what may improve and what may worsen",
    },
    "strategy_spec": "copy the assigned valid example nesting, then choose values",
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
