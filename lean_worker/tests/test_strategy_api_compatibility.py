from pathlib import Path


def _text(relative):
    root = Path(__file__).resolve().parents[1]
    return (root / relative).read_text(encoding="utf-8")


def test_daily_only_benchmark_does_not_request_hour_data():
    base = _text("runtime_support/alphaforge_base.py")
    classic = _text("strategies/approved/classic_30_stock_top3_momentum/main.py")
    ml = _text("strategies/approved/ml_30_stock_gradient_boosting/main.py")
    assert "def af_use_security_benchmark" in base
    assert "self.set_benchmark(benchmark_value)" in base
    assert "set_benchmark(self.spy)" not in classic
    assert "set_benchmark(self.spy)" not in ml
    assert "af_use_security_benchmark(self.spy)" in classic
    assert "af_use_security_benchmark(self.spy)" in ml


def test_top3_strategies_use_staged_rebalance():
    base = _text("runtime_support/alphaforge_base.py")
    classic = _text("strategies/approved/classic_30_stock_top3_momentum/main.py")
    ml = _text("strategies/approved/ml_30_stock_gradient_boosting/main.py")
    assert "def af_rebalance_to_weights" in base
    assert "phase 1 remove" in base
    assert "free_portfolio_value_percentage" in base
    assert "effective_target" in base
    assert "af_rebalance_to_weights(" in classic
    assert "af_rebalance_to_weights(" in ml
    assert "set_holdings(targets, True)" not in classic
    assert "set_holdings(targets, True)" not in ml


def test_partial_history_symbols_do_not_block_full_universe():
    classic = _text("strategies/approved/classic_30_stock_top3_momentum/main.py")
    ml = _text("strategies/approved/ml_30_stock_gradient_boosting/main.py")
    assert "ready_scores" in classic
    assert "all(indicator.is_ready" not in classic
    assert "skipped_symbols" in ml
    assert "for symbol in current_rows" in ml
    assert "ML insufficient history" not in ml


def test_ml_history_access_avoids_pandas_mapper_missing_key_exception():
    base = _text("runtime_support/alphaforge_base.py")
    ml = _text("strategies/approved/ml_30_stock_gradient_boosting/main.py")
    assert "def af_split_history_frames" in base
    assert "history.iloc[row_positions]" in base
    assert "af_split_history_frames(history)" in ml
    assert "history.loc[symbol]" not in ml
    assert "history.xs(symbol" not in ml
    assert "history_not_available_in_requested_window" in ml


def test_guided_low_volatility_uses_safe_history_and_staged_execution():
    guided = _text("strategies/approved/guided_30_stock_low_volatility/main.py")
    assert "af_split_history_frames(history)" in guided
    assert "self.af_rebalance_to_weights(" in guided
    assert "ALPHAFORGE_GUIDED_30_LOW_VOLATILITY_COMPLETED" in guided
