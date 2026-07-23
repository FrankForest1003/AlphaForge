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


def test_cash_buffer_is_a_single_shared_base_default():
    base = _text("runtime_support/alphaforge_base.py")
    strategies = [
        _text("strategies/approved/classic_30_stock_top3_momentum/main.py"),
        _text("strategies/approved/classic_30_stock_mean_reversion/main.py"),
        _text("strategies/approved/ml_30_stock_gradient_boosting/main.py"),
        _text("strategies/approved/hybrid_30_stock_ml_momentum_min_variance/main.py"),
    ]
    assert "self.settings.free_portfolio_value_percentage = 0.02" in base
    assert all("free_portfolio_value_percentage" not in strategy for strategy in strategies)


def test_top3_strategies_use_staged_rebalance():
    base = _text("runtime_support/alphaforge_base.py")
    classic = _text("strategies/approved/classic_30_stock_top3_momentum/main.py")
    ml = _text("strategies/approved/ml_30_stock_gradient_boosting/main.py")
    assert "def af_rebalance_to_weights" in base
    assert "def _af_submit_opening_orders" in base
    assert "opening price probe" not in base
    assert "def _af_submit_adjustment_phase" in base
    assert "self.limit_order(" in base
    assert "AlphaForge daily target repricing" in base
    assert "self.af_clear_pending_rebalance()" in base
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


def test_worker_exposes_read_only_behavior_details():
    service = _text("app/service.py")
    assert '@app.get("/v1/jobs/{run_id}/details")' in service
    assert 'result_path.parent / "alphaforge_details.json"' in service
    assert "path.relative_to(RESULTS_ROOT)" in service


def test_hybrid_exits_stale_holdings_and_caps_execution_gross():
    hybrid = _text(
        "strategies/approved/hybrid_30_stock_ml_momentum_min_variance/main.py"
    )
    assert "if symbol not in selected:" in hybrid
    assert "execution_weights[symbol] = 0.0" in hybrid
    assert "execution_gross = sum(" in hybrid
    assert "execution_cap = min(" in hybrid
    assert "if execution_gross > execution_cap" in hybrid
    assert "self.signal_allocation_weight = 0.70" in hybrid
    assert "self.minimum_variance_allocation_weight = 0.30" in hybrid
