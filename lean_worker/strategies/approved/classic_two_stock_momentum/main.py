from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class ClassicTwoStockMomentum(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2021-01-04"))
        end = datetime.fromisoformat(self._parameter("end_date", "2025-12-31"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.lookback = int(self._parameter("lookback", "126"))
        self.target_weight = float(self._parameter("target_weight", "0.95"))

        self.symbols = []
        for ticker in ["AAPL", "MSFT"]:
            security = self.add_equity(ticker, Resolution.DAILY)
            security.set_data_normalization_mode(DataNormalizationMode.RAW)
            security.set_leverage(1)
            self.symbols.append(self.af_track_symbol(security.symbol))
        self.reference_symbol = self.symbols[0]
        self.set_benchmark(lambda time: self.securities[self.reference_symbol].price)
        self.momentum = {s: self.roc(s, self.lookback, Resolution.DAILY) for s in self.symbols}
        self.pending_target = None
        self.pending_created_date = None
        self.set_warm_up(self.lookback + 1, Resolution.DAILY)
        self.schedule.on(
            self.date_rules.month_start(self.reference_symbol),
            self.time_rules.after_market_open(self.reference_symbol, 5),
            self.evaluate_signal,
        )
        self.schedule.on(
            self.date_rules.every_day(self.reference_symbol),
            self.time_rules.after_market_open(self.reference_symbol, 10),
            self.execute_pending_entry,
        )

    def on_alpha_data(self, data):
        pass

    def evaluate_signal(self):
        if self.is_warming_up or self.pending_target is not None:
            return
        if not all(indicator.is_ready for indicator in self.momentum.values()):
            return
        scores = {s: float(i.current.value) for s, i in self.momentum.items()}
        winner = max(scores, key=scores.get)
        self.af_record_signal("monthly_momentum", {
            "scores": {s.value: score for s, score in scores.items()},
            "winner": winner.value,
        })
        invested = [s for s in self.symbols if self.portfolio[s].invested]
        if scores[winner] <= 0:
            if invested:
                self.liquidate(tag="Risk-off: non-positive momentum")
            return
        if invested == [winner]:
            return
        if invested:
            self.pending_target = winner
            self.pending_created_date = self.time.date()
            self.liquidate(tag="Phase 1: exit old monthly winner")
        else:
            self.set_holdings(winner, self.target_weight, tag="Enter top momentum")

    def execute_pending_entry(self):
        if self.is_warming_up or self.pending_target is None:
            return
        if self.time.date() <= self.pending_created_date or self.transactions.get_open_orders() or self.portfolio.invested:
            return
        target = self.pending_target
        self.pending_target = None
        self.pending_created_date = None
        self.set_holdings(target, self.target_weight, tag="Phase 2: enter new winner")

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_CLASSIC_MOMENTUM_COMPLETED")
