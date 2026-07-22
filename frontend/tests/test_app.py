from __future__ import annotations

import os
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest


FRONTEND_ROOT = Path(__file__).resolve().parents[1]


def test_labelled_mock_overview_renders_without_exception(monkeypatch):
    monkeypatch.setenv("ALPHAFORGE_MOCK_MODE", "true")
    sys.path.insert(0, str(FRONTEND_ROOT))
    try:
        app = AppTest.from_file(str(FRONTEND_ROOT / "app.py"))
        app.run(timeout=30)
        assert not app.exception
    finally:
        sys.path.remove(str(FRONTEND_ROOT))


def test_light_theme_and_high_contrast_baseline_components_are_configured():
    config = (FRONTEND_ROOT / ".streamlit/config.toml").read_text(encoding="utf-8")
    source = (FRONTEND_ROOT / "app.py").read_text(encoding="utf-8")

    assert 'base = "light"' in config
    assert 'textColor = "#172033"' in config
    assert '[data-testid="stAlert"]' in source
    assert ".status-pill" in source
    assert ".run-card" in source
    assert "Normalized LEAN scorecard" in source
    assert "Highest Sharpe" in source
    assert "Max drawdown ↓" in source


def test_live_baseline_scorecard_renders_without_exception(monkeypatch):
    monkeypatch.setenv("ALPHAFORGE_MOCK_MODE", "false")
    sys.path.insert(0, str(FRONTEND_ROOT))
    try:
        from api_client import AlphaForgeAPI

        runs = []
        for index, (name, family, sharpe) in enumerate(
            [
                ("Momentum Rank", "Traditional", 0.72),
                ("Mean Reversion", "Traditional", 0.48),
                ("Gradient Boosting", "Machine Learning", 0.83),
                ("Hybrid ML + Minimum Variance", "Hybrid", 0.91),
            ],
            start=1,
        ):
            runs.append(
                {
                    "display_name": name,
                    "family": family,
                    "state": "completed",
                    "worker_run_id": f"test-run-{index}",
                    "eligible_for_comparison": True,
                    "summary": {
                        "sharpe_ratio": sharpe,
                        "cagr": 0.08 + index / 100,
                        "maximum_drawdown": 0.20 - index / 100,
                        "portfolio_turnover": 0.10 + index / 100,
                        "total_fees": 100 + index,
                        "total_orders": 20 + index,
                    },
                    "performance": {
                        "equity_curve": [
                            {"time": "2025-01-02", "portfolio_value": 100_000},
                            {"time": "2025-02-03", "portfolio_value": 101_000 + index},
                        ],
                        "drawdown_curve": [
                            {"time": "2025-01-02", "drawdown": 0},
                            {"time": "2025-02-03", "drawdown": 0.02 + index / 100},
                        ],
                    },
                }
            )

        monkeypatch.setattr(
            AlphaForgeAPI,
            "baselines",
            lambda self, battle_id, refresh=True: {
                "batch_id": "base-test",
                "contract_hash": "a" * 64,
                "state": "completed",
                "runs": runs,
                "error": None,
            },
        )

        app = AppTest.from_file(str(FRONTEND_ROOT / "app.py"))
        app.run(timeout=30)
        app.session_state["page"] = "baselines"
        app.session_state["unlocked_step"] = 2
        app.session_state["battle_id"] = "battle-test"
        app.run(timeout=30)

        assert not app.exception
        assert any(item.value == "Normalized LEAN scorecard" for item in app.subheader)
        assert len(app.tabs) == 5
    finally:
        sys.path.remove(str(FRONTEND_ROOT))
