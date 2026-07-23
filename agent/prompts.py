from __future__ import annotations

from pathlib import Path


DESIGNER_TRACKS = ("Traditional", "ML", "Hybrid")

TRACK_BRIEFS = {
    "Traditional": "Design a transparent strategy without machine learning.",
    "ML": "Design a genuine machine-learning strategy with time-ordered training and no look-ahead leakage.",
    "Hybrid": "Combine a transparent market signal with a genuine machine-learning component.",
}

DESIGNER_SYSTEM_PROMPT = """You are an expert QuantConnect LEAN Python strategy developer.
Create one complete, runnable strategy for the assigned design track. Use only data
available at each decision time. Return exactly one JSON object with one field named
source_code and no surrounding prose."""

REPAIR_SYSTEM_PROMPT = """You are an expert QuantConnect LEAN Python strategy repairer.
Diagnose the complete submitted strategy and its actual LEAN console log. Preserve the
assigned strategy family and shared run settings, fix the observed failure and related
defects in the whole file, and return exactly one JSON object with one field named
source_code and no surrounding prose."""

ACCEPTANCE_SYSTEM_PROMPT = """You are the AlphaForge strategy acceptance agent.
Audit one completed QuantConnect LEAN run against checks A1 through A5. Apply every
check exactly as written. Return one JSON object and no surrounding prose. Do not write
or modify strategy code."""

ACCEPTANCE_CHECK_IDS = ("A1", "A2", "A3", "A4", "A5")

ACCEPTANCE_RULES = """ALPHAFORGE ACCEPTANCE RULES

A1 ACTUAL INVESTMENT ACTIVITY
Use the Backend behavior facts to evaluate this conjunction:
filled_order_count > 0, invested_snapshot_count > 0, and max_gross_exposure > 0.
Record pass when the conjunction is true and fail when it is false. Cite all three
values as evidence.

A2 DATA-TO-ORDER CAUSAL PATH
Construct an execution proof with these ordered stages: available market rows; feature
rows; trained signal or model state; prediction or ranking values; target weights; order
submission; filled orders. For each stage, cite the source expression and the observed
execution fact that establishes its output. Record pass when the proof reaches filled
orders. Record fail at the first stage whose required output is absent.

For ML and Hybrid code, include separate numeric cardinality calculations for training
and inference. Each calculation states the available row count, each row loss caused by
pct_change/rolling/shift, the label horizon where applicable, and the surviving row
count after dropna. Include model-availability guards, score collection, target creation,
and early-return conditions in the proof. When A1 is fail, the execution proof ends
before filled orders and A2 is fail; identify the first interruption established by
the source and execution facts. When the evidence ends before the first interruption
can be localized, name the exact additional runtime value needed to complete the proof.

A3 DESIGN TRACK INTEGRITY
Traditional passes when the evidence traces a non-ML market signal into symbol selection
or target weights. ML passes when the evidence traces fitted model state through a
prediction into symbol selection or target weights. Hybrid passes when the evidence
traces both fitted-model predictions and an independent non-ML market signal into the
same final selection or target-weight decision. Cite the assignments and consumers that
establish each connection.

A4 TIME INTEGRITY
Construct a timeline for each training and trading path. State the decision timestamp,
the latest input bar end_time available to that decision, the feature timestamp, the
label timestamp for training rows, and the training cutoff used by each prediction.
Record pass when every input and trained parameter is available by its decision time.
Record fail when a cited timeline contains an input, label, or trained parameter from
after its decision time. A failure evidence item includes the two concrete timestamps
or relative offsets that establish this ordering.

A5 SHARED RUN SETTINGS
Map symbols, dates, initial cash, benchmark, fees, and slippage from each run_settings
field to the source expression that consumes it. Record pass when every mapping is
present and all traded stocks belong to run_settings.symbols. A selected subset satisfies
the symbol mapping, and the benchmark remains separate from the candidate stocks.

DECISION
Return accept only when A1, A2, A3, A4, and A5 all pass. Return revise when any check
fails. A revise response must contain a non-empty repair_request addressing the failed
causal or compliance issue. An accept response must set repair_request to null.
Build the repair_request from failed checks by carrying forward their cited execution
facts, source expressions, numeric calculations, and first interrupted stage. When the
first interruption requires an additional runtime value, request that value directly.

EVALUATION SCOPE
Acceptance evidence consists of actual investment activity, strategy causality, design
track integrity, time integrity, and shared-setting mappings. Profitability, baseline
outperformance, Sharpe, CAGR, drawdown, and order-volume preferences are displayed
results outside the acceptance decision.
"""

QC_TEMPLATE = '''from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm, af_split_history_frames


class UserStrategy(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2020-01-02"))
        end = datetime.fromisoformat(self._parameter("end_date", "2024-12-31"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.target_gross = 0.95

        tickers = [
            ticker.strip().upper()
            for ticker in self._parameter("symbols", "MSFT,AAPL,NVDA,GOOGL,AMZN").split(",")
            if ticker.strip()
        ]
        fee_bps = float(self._parameter("transaction_cost_bps", "10"))
        slippage_bps = float(self._parameter("slippage_bps", "5"))

        self.symbols = []
        for ticker in tickers:
            security = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                security,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            self.symbols.append(self.af_track_symbol(security.symbol))

        benchmark_ticker = self._parameter("benchmark", "SPY").strip().upper()
        benchmark = self.add_equity(benchmark_ticker, Resolution.DAILY)
        self.af_configure_security(benchmark)
        self.benchmark_symbol = benchmark.symbol
        self.af_use_security_benchmark(self.benchmark_symbol)

        # Canonical DataFrame history calls:
        # one_symbol = self.history(TradeBar, self.symbols[0], 252, Resolution.DAILY)
        # by_ticker = af_split_history_frames(
        #     self.history(self.symbols, 252, Resolution.DAILY)
        # )
        # Never index self.history[TradeBar](...) as a pandas DataFrame.
        # Keep total absolute target weights at or below self.target_gross.
        # For a long-only basket on Daily data, submit a {Symbol: weight} mapping
        # with self.af_rebalance_to_weights(target_weights, "rebalance reason") so
        # reductions fill before new purchases are sized.
        # Add the strategy's indicators, models, schedules, and state here.

    def on_alpha_data(self, data):
        # Implement event-driven strategy logic here when needed.
        pass
'''


def load_lean_text(path: Path) -> str:
    text_path = path / "writing-algorithms-python.txt"
    if not text_path.is_file():
        raise FileNotFoundError(f"LEAN documentation text is missing: {text_path}")
    return text_path.read_text(encoding="utf-8")
