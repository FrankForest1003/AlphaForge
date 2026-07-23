from agent.validation import validate_candidate_source


def valid_source(track: str) -> str:
    ml = ""
    if track in {"ML", "Hybrid"}:
        ml = """
        self.model.fit([[0.0], [1.0]], [0.0, 1.0])
        prediction = self.model.predict([[0.5]])[0]
        self.af_record_ml_training({
            "model_type": "Test",
            "training_rows": 2,
            "label_horizon_days": 1,
            "random_seed": 42,
            "feature_names": ["value"],
        })
        self.af_record_ml_prediction(
            {"symbol": "MSFT", "predicted_alpha": prediction, "rank": 1, "selected": True}
        )
"""
    transparent = ""
    if track in {"Traditional", "Hybrid"}:
        transparent = (
            'momentum = 1.0\n'
            '        self.af_record_signal("momentum", {"symbol": "MSFT", "value": momentum})'
        )
    return f'''from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class UserStrategy(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        symbols = self._parameter("symbols", "MSFT,AAPL,NVDA,GOOGL,AMZN")
        start_date = self._parameter("start_date", "2020-01-02")
        end_date = self._parameter("end_date", "2024-12-31")
        initial_cash = self._parameter("initial_cash", "100000")
        benchmark = self._parameter("benchmark", "SPY")
        transaction_cost_bps = self._parameter("transaction_cost_bps", "10")
        slippage_bps = self._parameter("slippage_bps", "5")
        self.af_configure_security(None)
        self.af_track_symbol(None)
        self.schedule.on(self.date_rules.month_start("MSFT"), self.time_rules.after_market_open("MSFT", 1), self.rebalance)
{ml.rstrip()}

    def rebalance(self):
        {transparent}
        self.af_rebalance_to_weights({{}}, "test")
'''


def diagnostic_codes(report):
    return {item["code"] for item in report["diagnostics"]}


def test_stable_track_sources_pass_preflight():
    for track in ("Traditional", "ML", "Hybrid"):
        report = validate_candidate_source(valid_source(track), track)
        assert report["status"] == "passed"
        assert report["diagnostics"] == []
        assert len(report["source_sha256"]) == 64


def test_trace_failures_are_rejected_before_lean_submission():
    source = valid_source("ML").replace(
        "self.model.fit([[0.0], [1.0]], [0.0, 1.0])",
        "matrix = xgb.DMatrix([[0.0], [1.0]])",
    )
    report = validate_candidate_source(source, "ML")
    assert report["status"] == "failed"
    assert {"UNSTABLE_LEAN_PATTERN", "MISSING_ML_FLOW"}.issubset(
        diagnostic_codes(report)
    )


def test_history_subscript_and_direct_portfolio_bypass_are_rejected():
    source = valid_source("Traditional").replace(
        'self.af_rebalance_to_weights({}, "test")',
        "frame = self.history[TradeBar](self.symbols, 20, Resolution.DAILY)\n"
        "        self.set_holdings(self.symbols[0], 1.0)",
    )
    report = validate_candidate_source(source, "Traditional")
    assert report["status"] == "failed"
    assert "LEAN_HISTORY_SUBSCRIPT" in diagnostic_codes(report)
    assert "MISSING_ALPHAFORGE_API" in diagnostic_codes(report)
    assert "UNSTABLE_LEAN_PATTERN" in diagnostic_codes(report)


def test_track_integrity_is_checked_deterministically():
    traditional_with_model = valid_source("ML")
    report = validate_candidate_source(traditional_with_model, "Traditional")
    assert report["status"] == "failed"
    assert "TRACK_MISMATCH" in diagnostic_codes(report)


def test_schedule_builder_and_wrong_evidence_signatures_are_rejected():
    source = valid_source("ML").replace(
        'self.schedule.on(self.date_rules.month_start("MSFT"), self.time_rules.after_market_open("MSFT", 1), self.rebalance)',
        'self.schedule.on(self.date_rules.month_start("MSFT"), '
        'self.time_rules.after_market_open("MSFT", 1)).do(self.rebalance)',
    ).replace(
        '''self.af_record_ml_training({
            "model_type": "Test",
            "training_rows": 2,
            "label_horizon_days": 1,
            "random_seed": 42,
            "feature_names": ["value"],
        })''',
        'self.af_record_ml_training("Test", 2, 1, 42, ["value"])',
    ).replace(
        '{"symbol": "MSFT", "predicted_alpha": prediction, "rank": 1, "selected": True}',
        'symbol="MSFT", prediction=prediction, rank=1, selected=True',
    )

    report = validate_candidate_source(source, "ML")
    assert report["status"] == "failed"
    assert {
        "LEAN_SCHEDULE_SIGNATURE",
        "LEAN_SCHEDULE_BUILDER",
        "ALPHAFORGE_EVIDENCE_SIGNATURE",
    }.issubset(diagnostic_codes(report))


def test_evidence_payload_keys_are_checked():
    source = valid_source("ML").replace(
        '"label_horizon_days": 1,',
        '"horizon": 1,',
    )
    report = validate_candidate_source(source, "ML")
    assert report["status"] == "failed"
    assert "ALPHAFORGE_EVIDENCE_KEYS" in diagnostic_codes(report)


def test_impossible_negative_iloc_guard_is_rejected():
    source = valid_source("Traditional").replace(
        'self.af_rebalance_to_weights({}, "test")',
        '''end_idx = -self.gap - 1
        start_idx = end_idx - self.momentum_window
        if start_idx < 0:
            return
        price = frame.iloc[start_idx]["close"]
        self.af_rebalance_to_weights({}, "test")''',
    )
    report = validate_candidate_source(source, "Traditional")
    assert report["status"] == "failed"
    assert "IMPOSSIBLE_ILOC_GUARD" in diagnostic_codes(report)


def test_forward_labels_cannot_be_filled_with_zero():
    source = valid_source("ML").replace(
        "prediction = self.model.predict([[0.5]])[0]",
        "label = close.pct_change(21).shift(-21).fillna(0)\n"
        "        prediction = self.model.predict([[0.5]])[0]",
    )
    report = validate_candidate_source(source, "ML")
    assert report["status"] == "failed"
    assert "ML_FORWARD_LABEL_FILL" in diagnostic_codes(report)


def test_agent_cannot_shadow_alphaforge_evidence_methods():
    source = valid_source("ML").replace(
        "\n    def rebalance(self):",
        "\n    def af_record_ml_training(self, payload):\n"
        "        pass\n\n"
        "    def rebalance(self):",
    )
    report = validate_candidate_source(source, "ML")
    assert report["status"] == "failed"
    assert "ALPHAFORGE_BASE_OVERRIDE" in diagnostic_codes(report)
