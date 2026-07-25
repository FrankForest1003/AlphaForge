from __future__ import annotations

import ast

from app.schemas import GuidedHumanStrategy
from app.services.baseline_service import (
    build_battle_analysis,
    build_guided_human_source,
    build_robustness_verdict,
)


def _entry(
    *,
    state: str,
    cagr: float,
    sharpe: float,
    drawdown: float,
    volatility: float,
    turnover: float,
) -> dict:
    return {
        "state": state,
        "summary": {
            "cagr": cagr,
            "sharpe_ratio": sharpe,
            "maximum_drawdown": drawdown,
            "end_equity": 200_000,
        },
        "analysis": {
            "statistics": {
                "annualized_volatility": volatility,
                "annualized_turnover": turnover,
                "total_fees": 1_000,
            }
        },
        "behavior_evidence": {
            "filled_order_count": 20,
            "invested_snapshot_count": 100,
            "max_gross_exposure": 0.90,
        },
    }


def test_advanced_guided_strategy_compiles_through_fixed_template():
    guided = GuidedHumanStrategy(
        level="advanced",
        signal="momentum_low_volatility",
        lookback_days=90,
        secondary_lookback_days=42,
        primary_signal_weight=0.70,
        holdings=5,
        weighting="inverse_volatility",
        gross_exposure=0.90,
        max_position_weight=0.25,
        rebalance_threshold=0.03,
        market_trend_filter=True,
        market_sma_window=150,
    )

    source = build_guided_human_source(guided)

    ast.parse(source)
    assert '"momentum_low_volatility"' not in source
    assert '"kind":"return"' in source
    assert '"kind":"volatility"' in source
    assert '"weighting":"inverse_volatility"' in source


def test_score_v2_prioritizes_sharpe_and_cagr_over_secondary_components():
    human = _entry(
        state="completed",
        cagr=0.30,
        sharpe=1.40,
        drawdown=0.24,
        volatility=0.30,
        turnover=3.0,
    )
    human.update({"mode": "code"})
    ai = _entry(
        state="accepted",
        cagr=0.18,
        sharpe=0.85,
        drawdown=0.18,
        volatility=0.22,
        turnover=1.0,
    )
    ai.update({"track": "Traditional", "design": {"thesis": "test"}})
    run = {
        "settings": {"initial_cash": 100_000},
        "baselines": [],
        "human": human,
        "candidates": [ai],
    }

    analysis = build_battle_analysis(run)
    cards = {item["id"]: item for item in analysis["judge"]["scorecards"]}

    assert analysis["judge"]["method"] == "deterministic_weighted_score_v2"
    assert cards["human"]["score"] > cards["ai-traditional"]["score"]
    assert analysis["judge"]["weights"]["sharpe_ratio"] == 0.35
    assert analysis["judge"]["weights"]["cagr"] == 0.30


def test_learning_review_recommends_bounded_values_from_human_settings():
    human = _entry(
        state="completed",
        cagr=0.18,
        sharpe=0.70,
        drawdown=0.34,
        volatility=0.31,
        turnover=3.0,
    )
    human.update(
        {
            "mode": "guided",
            "guided": {
                "holdings": 3,
                "weighting": "equal",
                "gross_exposure": 0.90,
                "max_position_weight": 0.45,
                "rebalance_threshold": 0.02,
            },
        }
    )
    ai = _entry(
        state="accepted",
        cagr=0.22,
        sharpe=1.10,
        drawdown=0.22,
        volatility=0.23,
        turnover=1.0,
    )
    ai.update({"track": "Traditional", "design": {"thesis": "test"}})

    analysis = build_battle_analysis(
        {
            "battle_id": "battle-test",
            "settings": {"initial_cash": 100_000},
            "baselines": [],
            "human": human,
            "candidates": [ai],
        }
    )
    recommendations = {
        item["parameter_path"]: item
        for item in analysis["education_summary"]["human_feedback"][
            "parameter_recommendations"
        ]
    }

    assert recommendations["guided.weighting"]["recommended_value"] == (
        "inverse_volatility"
    )
    assert recommendations["guided.max_position_weight"]["recommended_value"] == 0.40
    assert recommendations["guided.rebalance_threshold"]["recommended_value"] == 0.03


def test_robustness_v2_requires_every_scenario_and_controls_worst_case():
    primary = {
        "cagr": 0.20,
        "sharpe_ratio": 1.0,
        "maximum_drawdown": 0.20,
    }
    scenarios = []
    for scenario_id in (
        "recent_regime",
        "delayed_start",
        "friction_2x",
        "universe_dropout",
    ):
        scenarios.append(
            {
                "id": scenario_id,
                "state": "completed",
                "summary": {
                    "cagr": 0.18,
                    "sharpe_ratio": 0.90,
                    "maximum_drawdown": 0.22,
                },
                "behavior_evidence": {
                    "filled_order_count": 10,
                    "max_gross_exposure": 0.8,
                },
            }
        )

    verdict = build_robustness_verdict(primary, scenarios)

    assert verdict["policy_version"] == "deterministic-robustness-v2"
    assert verdict["grade"] == "robust"
    assert verdict["worst_scenario_score"] >= 55
    assert all("thresholds" in scenario for scenario in scenarios)

    scenarios[0]["state"] = "failed"
    failed = build_robustness_verdict(primary, scenarios)
    assert failed["grade"] == "insufficient"
    assert "recent_regime" in failed["critical_failures"]
