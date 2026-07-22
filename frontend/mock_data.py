from __future__ import annotations

import math

import pandas as pd


COLORS = {
    "Human": "#0F766E",
    "Traditional": "#2563EB",
    "ML": "#7C3AED",
    "Hybrid": "#D97706",
    "Baseline": "#64748B",
}


RESULTS = pd.DataFrame(
    [
        ("Your Strategy", "Human", 1.08, 14.7, -17.8, 18.2, 0.71),
        ("Momentum", "Baseline", 0.91, 12.4, -19.5, 22.8, 0.62),
        ("Mean Reversion", "Baseline", 0.68, 8.9, -21.7, 39.4, 0.49),
        ("Gradient Boosting", "Baseline", 0.96, 13.1, -18.9, 31.7, 0.65),
        ("Random Forest", "Baseline", 0.82, 10.8, -20.1, 35.2, 0.57),
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
    ("04", "Random Forest", "Average many decision trees", "Robust to noisy features but can dilute weak signals.", "Bagging · feature subsampling"),
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
    {"stage": "Public Evidence", "owner": "Deterministic module", "finding": "Momentum and GBM lead the public baselines; all four weaken in risk-off periods.", "output": "Four-baseline evidence bundle", "chart": {"Momentum": .91, "Mean Reversion": .68, "GBM": .96, "Random Forest": .82}},
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


LEAN_TEMPLATE = '''from AlgorithmImports import *

class UserStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetCash(100000)
        self.spy = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.sma = self.SMA(self.spy, 200, Resolution.Daily)

    def OnData(self, data: Slice):
        if not self.sma.IsReady:
            return
        if self.Securities[self.spy].Price > self.sma.Current.Value:
            self.SetHoldings(self.spy, 1.0)
        else:
            self.Liquidate()
'''
