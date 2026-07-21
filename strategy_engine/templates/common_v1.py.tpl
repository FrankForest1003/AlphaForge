from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm, af_split_history_frames
import numpy as np
import pandas as pd
__MODEL_IMPORT__


class __ALGORITHM_CLASS__(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "__START_DATE__"))
        end = datetime.fromisoformat(self._parameter("end_date", "__END_DATE__"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "__INITIAL_CASH__")))
        self.symbols = []
        self.symbol_by_ticker = {}
        for ticker in __SYMBOLS__:
            security = self.add_equity(ticker, Resolution.DAILY)
            security.set_data_normalization_mode(DataNormalizationMode.RAW)
            security.set_leverage(1)
            symbol = self.af_track_symbol(security.symbol)
            self.symbols.append(symbol)
            self.symbol_by_ticker[ticker] = symbol

        benchmark = self.symbol_by_ticker.get("SPY")
        if benchmark is None:
            benchmark_security = self.add_equity("SPY", Resolution.DAILY)
            benchmark_security.set_data_normalization_mode(DataNormalizationMode.RAW)
            benchmark_security.set_leverage(1)
            benchmark = benchmark_security.symbol
        self.af_use_security_benchmark(benchmark)

        self.top_k = __TOP_K__
        self.target_gross = 0.95
        self.max_position_weight = __MAX_POSITION_WEIGHT__
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.settings.free_portfolio_value_percentage = 0.02
        self.set_warm_up(__WARMUP_DAYS__, Resolution.DAILY)
        anchor = self.symbols[0]
        self.schedule.on(
            self.date_rules.month_start(anchor),
            self.time_rules.after_market_open(anchor, 30),
            self.rebalance,
        )
        self._last_rebalance_date = None

    def rebalance(self):
        if self.is_warming_up or self._last_rebalance_date == self.time.date():
            return
        if self.transactions.get_open_orders():
            return
        self._last_rebalance_date = self.time.date()
        raw_scores = self.compute_scores()
        scores = {
            symbol: float(score)
            for symbol, score in raw_scores.items()
            if symbol in self.symbols
            and np.isfinite(score)
            and self.securities[symbol].has_data
            and float(self.securities[symbol].price) > 0
        }
        if len(scores) < self.top_k:
            self.af_record_signal(
                "alphaforge_insufficient_eligible_symbols",
                {
                    "eligible_count": len(scores),
                    "required_count": self.top_k,
                },
            )
            return
        selected = [
            symbol
            for symbol, _ in sorted(
                scores.items(), key=lambda item: item[1], reverse=True
            )[: self.top_k]
        ]
        per_asset = min(
            self.max_position_weight,
            self.target_gross / len(selected),
        )
        target_weights = {symbol: per_asset for symbol in selected}
        self.af_record_signal(
            "alphaforge_monthly_top_k",
            {
                "scores": {symbol.value: score for symbol, score in scores.items()},
                "selected": [symbol.value for symbol in selected],
                "target_weight_each": per_asset,
                "target_gross": per_asset * len(selected),
            },
        )
        self.af_rebalance_to_weights(target_weights, "AlphaForge monthly rebalance")

    def on_alpha_end(self):
        self.debug("__COMPLETION_MARKER__")

__ROUTE_METHODS__
