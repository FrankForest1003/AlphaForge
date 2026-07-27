from __future__ import annotations

import ast
import json

import pytest
from pydantic import ValidationError

from app.schemas.strategy_template import StrategyTemplateSpec
from app.services.strategy_template import (
    TEMPLATE_MARKER,
    compile_strategy_source,
    strategy_spec_json_schema,
)


def traditional_spec():
    return {
        "schema_version": "template-v1",
        "strategy_name": "Dual Horizon Transparent Rank",
        "track": "Traditional",
        "thesis": "Medium-term relative strength and lower volatility improve ranking stability.",
        "signal": {
            "components": [
                {
                    "feature": {"kind": "return", "window": 126},
                    "direction": "higher",
                    "weight": 0.65,
                },
                {
                    "feature": {"kind": "volatility", "window": 42},
                    "direction": "lower",
                    "weight": 0.35,
                },
            ]
        },
        "selection": {"top_k": 5},
        "portfolio": {
            "weighting": "inverse_volatility",
            "gross_exposure": 0.95,
            "max_position_weight": 0.25,
        },
        "schedule": {"frequency": "monthly"},
        "risk": {"market_trend_filter": True, "market_sma_window": 180},
    }


def ml_spec(track="ML"):
    payload = {
        "schema_version": "template-v1",
        "strategy_name": "Flexible Cross Sectional Learner",
        "track": track,
        "thesis": "A pooled model can rank medium-horizon excess returns from stable features.",
        "model": {
            "algorithm": "extra_trees",
            "features": [
                {"kind": "return", "window": 21},
                {"kind": "return", "window": 126},
                {"kind": "volatility", "window": 42},
                {"kind": "relative_return", "window": 63},
                {"kind": "rsi", "window": 14},
            ],
            "target": "excess_return",
            "horizon_days": 42,
            "pooled_training_rows": 504,
            "retrain_every_rebalances": 3,
            "n_estimators": 180,
            "max_depth": 4,
            "min_samples_leaf": 8,
        },
        "selection": {"top_k": 5},
        "portfolio": {
            "weighting": "blend_score_minimum_variance",
            "gross_exposure": 0.90,
            "max_position_weight": 0.25,
            "volatility_window": 84,
            "minimum_variance_blend": 0.40,
        },
        "schedule": {"frequency": "weekly", "minutes_after_open": 45},
        "risk": {
            "market_trend_filter": False,
            "stop_loss": 0.15,
            "maximum_drawdown": 0.25,
            "cooldown_days": 30,
        },
    }
    if track == "Hybrid":
        payload["signal"] = {
            "components": [
                {
                    "feature": {"kind": "sma_gap", "window": 100},
                    "direction": "higher",
                    "weight": 0.60,
                },
                {
                    "feature": {"kind": "relative_return", "window": 63},
                    "direction": "higher",
                    "weight": 0.40,
                },
            ]
        }
        payload["selection"]["hybrid_model_weight"] = 0.55
    return payload


@pytest.mark.parametrize(
    "payload",
    [traditional_spec(), ml_spec(), ml_spec("Hybrid")],
)
def test_supported_tracks_compile_to_one_parseable_template(payload):
    source = compile_strategy_source(payload)

    ast.parse(source)
    assert TEMPLATE_MARKER not in source
    assert "class UserStrategy(AlphaForgeBaseAlgorithm)" in source
    assert "self.history(history_symbols, self.history_bars" in source
    assert 'close.shift(-horizon) / close - 1.0' in source
    assert '"template_final_decision"' not in source


def test_compilation_is_deterministic_and_embeds_data_not_agent_code():
    payload = traditional_spec()
    payload["strategy_name"] = 'Safe "quoted" name'

    first = compile_strategy_source(payload)
    second = compile_strategy_source(payload)

    assert first == second
    assert "__ALPHAFORGE_STRATEGY_SPEC_SHA256__" not in first
    tree = ast.parse(first)
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "STRATEGY_SPEC"
            for target in node.targets
        )
    )
    embedded_json = ast.literal_eval(assignment.value.args[0])
    assert json.loads(embedded_json)["strategy_name"] == 'Safe "quoted" name'


def test_track_contract_rejects_hybrid_without_both_components():
    payload = ml_spec("Hybrid")
    payload.pop("signal")

    with pytest.raises(ValidationError, match="Hybrid requires both"):
        StrategyTemplateSpec.model_validate(payload)


def test_position_cap_may_leave_cash_below_requested_exposure():
    payload = traditional_spec()
    payload["selection"]["top_k"] = 3
    payload["portfolio"]["gross_exposure"] = 0.95
    payload["portfolio"]["max_position_weight"] = 0.30

    validated = StrategyTemplateSpec.model_validate(payload)

    assert validated.selection.top_k == 3
    assert validated.portfolio.gross_exposure == pytest.approx(0.95)
    assert (
        validated.selection.top_k * validated.portfolio.max_position_weight
        == pytest.approx(0.90)
    )
    ast.parse(compile_strategy_source(validated))


def test_agent_contract_contains_parameters_but_no_python_source_field():
    schema = strategy_spec_json_schema()
    properties = schema["properties"]

    assert "track" in properties
    assert "signal" in properties
    assert "model" in properties
    assert "portfolio" in properties
    assert "source_code" not in properties
