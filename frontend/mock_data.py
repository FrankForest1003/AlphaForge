from __future__ import annotations

import math

import pandas as pd


COLORS = {
    "Human": "#0F766E",
    "Traditional": "#2563EB",
    "ML": "#7C3AED",
    "Machine Learning": "#7C3AED",
    "Hybrid": "#D97706",
    "Baseline": "#64748B",
}


RESULTS = pd.DataFrame(
    [
        ("Your Strategy", "Human", 1.08, 14.7, -17.8, 18.2, 0.71),
        ("Momentum", "Baseline", 0.91, 12.4, -19.5, 22.8, 0.62),
        ("Mean Reversion", "Baseline", 0.68, 8.9, -21.7, 39.4, 0.49),
        ("Gradient Boosting", "Baseline", 0.96, 13.1, -18.9, 31.7, 0.65),
        ("Hybrid ML + Min Variance", "Baseline", 1.02, 14.2, -17.1, 28.5, 0.68),
        ("AI Traditional", "Traditional", 1.14, 15.3, -15.9, 20.6, 0.76),
        ("AI ML", "ML", 1.02, 14.1, -18.2, 30.9, 0.67),
        ("AI Hybrid", "Hybrid", 1.23, 16.4, -14.6, 24.1, 0.81),
    ],
    columns=["Strategy", "Track", "Sharpe", "CAGR", "MDD", "Turnover", "Robustness"],
)


BASELINE_LESSONS = [
    ("01", "Momentum", "Follow persistent trends", "Strong in directional markets; vulnerable to reversals.", "12-month return · monthly Top 3"),
    ("02", "Mean Reversion", "Buy temporary weakness", "Can work in ranges; may catch a falling asset.", "Z-score · controlled entry/exit"),
    ("03", "Gradient Boosting", "Combine nonlinear signals", "Flexible predictions need strict time-aware validation.", "Returns · RSI · volatility · SMA gap"),
    ("04", "Hybrid ML + Minimum Variance", "Separate ranking from sizing", "Expected return and covariance solve different portfolio decisions.", "GBM · momentum · Ledoit-Wolf"),
]


CANDIDATES = {
    "Traditional": {
        "id": "AI-T-R1", "title": "Regime-Aware Momentum", "risk": "Low–Medium",
        "thesis": "Keep interpretable trend signals, reduce exposure below the market regime filter.",
        "changes": ["Blend 21/63/126-day momentum", "QQQ 200-day SMA regime gate", "35% position cap"],
        "weights": {"Momentum": 55, "Risk gate": 25, "Volatility": 20},
    },
    "ML": {
        "id": "AI-ML-R1", "title": "Cross-Sectional GBM", "risk": "Medium–High",
        "thesis": "Rank next-month relative return with a compact, leakage-controlled feature set.",
        "changes": ["Walk-forward training only", "Five interpretable features", "Monthly Top 3 ranking"],
        "weights": {"Momentum": 31, "SMA gap": 24, "Volatility": 20, "RSI": 15, "Volume": 10},
    },
    "Hybrid": {
        "id": "AI-H-R1", "title": "Guarded Signal Fusion", "risk": "Medium",
        "thesis": "Use ML as auxiliary evidence while the stable classic signal remains dominant.",
        "changes": ["85% classic + 15% ML score", "Ledoit-Wolf risk allocation", "Turnover penalty"],
        "weights": {"Traditional": 85, "ML": 15},
    },
}


AGENT_EVENTS = [
    {"stage": "Public Evidence", "owner": "Deterministic module", "finding": "Momentum, mean reversion, GBM and the contributed Hybrid provide four public reference points.", "output": "Four-baseline evidence bundle", "chart": {"Momentum": .91, "Mean Reversion": .68, "GBM": .96, "Hybrid": 1.02}},
    {"stage": "Traditional Designer", "owner": "AI Designer", "finding": "Long-horizon trend is useful, but regime protection is missing.", "output": "Regime-Aware Momentum spec", "chart": {"Signal": 55, "Risk gate": 25, "Sizing": 20}},
    {"stage": "ML Designer", "owner": "AI Designer", "finding": "A small feature set is easier to validate and explain.", "output": "Walk-forward GBM spec", "chart": {"Momentum": 31, "SMA gap": 24, "Volatility": 20, "RSI": 15, "Volume": 10}},
    {"stage": "Hybrid Designer", "owner": "AI Designer", "finding": "ML adds information but is not stable enough to dominate.", "output": "85/15 guarded fusion spec", "chart": {"Traditional": 85, "ML": 15}},
    {"stage": "DSL Builder", "owner": "Deterministic module", "finding": "All required strategy fields are expressible by capability registry v1.", "output": "3 immutable StrategySpec artifacts", "chart": {"Schema": 100, "Semantic": 100, "Capability": 100, "Contract": 100}},
    {"stage": "Code Risk", "owner": "Safety Agent", "finding": "No future-data access, hidden leverage or unrestricted I/O detected.", "output": "3 pass · 2 warnings acknowledged", "chart": {"Leakage": 0, "Leverage": 0, "I/O": 0, "Warnings": 2}},
    {"stage": "LEAN Validation", "owner": "LEAN Worker", "finding": "All candidates compile and complete deterministic smoke runs.", "output": "3 run IDs + result hashes", "chart": {"Traditional": 100, "ML": 100, "Hybrid": 100}},
    {"stage": "Candidate Selector", "owner": "Deterministic selector", "finding": "Hybrid leads risk-adjusted performance and robustness.", "output": "AI-H-R1 selected as AI Champion", "chart": {"Traditional": 76, "ML": 67, "Hybrid": 81}},
]


def equity_curve(label: str, months: int = 60) -> pd.DataFrame:
    seeds = {"Human": (0.010, 0.025), "Traditional": (0.011, 0.020), "ML": (0.0105, 0.027), "Hybrid": (0.012, 0.019)}
    drift, wave = seeds[label]
    values = [100.0]
    for i in range(1, months):
        shock = wave * math.sin(i * 0.71) + 0.009 * math.cos(i * 0.23)
        values.append(values[-1] * (1 + drift + shock))
    return pd.DataFrame({"Month": range(months), "Portfolio": values, "Strategy": label})


LEAN_TEMPLATE = '''from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm, af_split_history_frames


class UserStrategy(AlphaForgeBaseAlgorithm):
    """Runnable starter: trend-quality ranking under the locked ExperimentContract.

    Safe editing area: change the score inside rebalance(). Keep the class name,
    three hook methods, contract parameters, execution helpers, and final marker.
    """

    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2016-01-04"))
        end = datetime.fromisoformat(self._parameter("end_date", "2026-06-30"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))

        tickers = [
            item.strip().upper()
            for item in self._parameter("symbols", "MSFT,AAPL,NVDA,GOOGL,AMZN").split(",")
            if item.strip()
        ]
        self.top_k = int(self._parameter("top_k", "3"))
        self.target_gross = float(self._parameter("target_gross", "0.95"))
        self.max_weight = float(self._parameter("max_position_weight", "0.35"))
        fee_bps = float(self._parameter("transaction_cost_bps", "10"))
        slippage_bps = float(self._parameter("slippage_bps", "5"))

        self.symbols = []
        for ticker in tickers:
            security = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                security, fee_bps=fee_bps, slippage_bps=slippage_bps
            )
            self.symbols.append(self.af_track_symbol(security.symbol))

        spy = self.add_equity("SPY", Resolution.DAILY)
        qqq = self.add_equity("QQQ", Resolution.DAILY)
        self.af_configure_security(spy)
        self.af_configure_security(qqq)
        self.spy, self.qqq = spy.symbol, qqq.symbol
        self.af_use_security_benchmark(self.spy)
        self.market_sma = self.sma(self.qqq, 200, Resolution.DAILY)
        self.set_warm_up(205, Resolution.DAILY)
        self.schedule.on(
            self.date_rules.month_start(self.symbols[0]),
            self.time_rules.after_market_open(self.symbols[0], 30),
            self.rebalance,
        )

    def on_alpha_data(self, data):
        # Scheduled rebalance owns the trading decision; keep this hook present.
        pass

    def rebalance(self):
        if self.is_warming_up or not self.market_sma.is_ready:
            return
        if self.securities[self.qqq].price <= self.market_sma.current.value:
            self.af_liquidate_all("Market risk gate")
            return

        history = self.history(self.symbols, 127, Resolution.DAILY)
        frames = af_split_history_frames(history)
        scores = {}
        for symbol in self.symbols:
            frame = frames.get(symbol.value)
            if frame is None or "close" not in frame.columns:
                continue
            close = frame["close"].astype(float).dropna()
            if len(close) < 127:
                continue
            momentum = float(close.iloc[-1] / close.iloc[-64] - 1.0)
            trend_gap = float(close.iloc[-1] / close.tail(100).mean() - 1.0)
            volatility = float(close.pct_change().dropna().tail(63).std())
            if momentum > 0 and trend_gap > 0 and volatility > 0:
                # Safe editing area: combine only trailing information here.
                scores[symbol] = momentum + 0.5 * trend_gap - 0.25 * volatility

        selected = [
            symbol for symbol, _ in
            sorted(scores.items(), key=lambda item: item[1], reverse=True)[: self.top_k]
        ]
        if not selected:
            self.af_liquidate_all("No eligible trend-quality candidates")
            return
        weight = min(self.max_weight, self.target_gross / len(selected))
        self.af_rebalance_to_weights(
            {symbol: weight for symbol in selected},
            "Monthly custom trend-quality rebalance",
        )

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_USER_STRATEGY_COMPLETED")
'''
