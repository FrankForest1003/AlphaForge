from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
TICKERS = [
    "MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ASML", "AMD", "ORCL",
    "JPM", "BRK.B", "V", "LLY", "JNJ", "ABBV", "TMO", "WMT", "COST", "PG",
    "KO", "MCD", "CAT", "HON", "UNP", "ETN", "XOM", "LIN", "NEE", "PLD",
]


def catalog():
    return {
        "tradable_symbols": [
            {"display_ticker": ticker, "sector": "Test"} for ticker in TICKERS
        ],
        "benchmarks": ["SPY"],
        "default_symbols": TICKERS[:5],
    }


def test_create_view_renders_shared_settings_human_builder_and_checkbox_universe(monkeypatch):
    sys.path.insert(0, str(FRONTEND_ROOT))
    try:
        from api_client import AlphaForgeAPI

        monkeypatch.setattr(AlphaForgeAPI, "universe", lambda self: catalog())
        app = AppTest.from_file(str(FRONTEND_ROOT / "app.py"))
        app.run(timeout=30)

        assert not app.exception
        assert len(app.checkbox) == 30
        assert sum(bool(item.value) for item in app.checkbox) == 5
        assert any(item.label == "Start date" for item in app.date_input)
        assert any(item.label == "End date" for item in app.date_input)
        assert any(item.label == "Initial cash" for item in app.number_input)
        assert any(item.label == "Benchmark" for item in app.selectbox)
        assert any(item.label == "Transaction cost (bps)" for item in app.number_input)
        assert any(item.label == "Slippage (bps)" for item in app.number_input)
        assert any(item.label == "Start full run" for item in app.button)
        assert any(item.label == "Signal" for item in app.selectbox)
        assert any(item.label == "Lookback" for item in app.selectbox)
        assert any(item.label == "Rebalance" for item in app.selectbox)
        assert any(item.label == "Holdings" for item in app.selectbox)
    finally:
        sys.path.remove(str(FRONTEND_ROOT))


def test_frontend_contains_complete_review_history_view():
    source = (FRONTEND_ROOT / "app.py").read_text(encoding="utf-8")
    assert "Review history" in source
    assert 'report.get("checks", [])' in source
    assert 'item.get("behavior_evidence")' in source
    assert 'report["repair_request"]' in source


def test_frontend_contains_human_modes_live_polling_and_run_navigation():
    source = (FRONTEND_ROOT / "app.py").read_text(encoding="utf-8")
    assert "Guided builder" in source
    assert "Complete Python code" in source
    assert '"human_strategy": human_payload' in source
    assert '@st.fragment(run_every="3s")' in source
    assert 'st.query_params["run_id"]' in source
    assert "Strategy lab" in source


def test_frontend_does_not_explain_internal_pipeline_in_product_copy():
    source = (FRONTEND_ROOT / "app.py").read_text(encoding="utf-8")
    assert "4 baselines · 1 Human · 3 parallel Designers" not in source
    assert "all eight strategies" not in source
    assert "launch three DeepSeek Designers in parallel" not in source
    assert "The Backend turns these four choices" not in source
    assert "The Worker executes it as supplied" not in source
