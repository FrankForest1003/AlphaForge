from AlgorithmImports import *
import numpy as np
import pandas as pd
__MODEL_IMPORT__


class AlphaForgeAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(__START_YEAR__, __START_MONTH__, __START_DAY__)
        self.SetEndDate(__END_YEAR__, __END_MONTH__, __END_DAY__)
        self.SetCash(__INITIAL_CASH__)
        self.symbols = {}
        for ticker in __SYMBOLS__:
            self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
        self.top_k = __TOP_K__
        self.max_position_weight = __MAX_POSITION_WEIGHT__
        self.SetWarmUp(__WARMUP_DAYS__, Resolution.Daily)
        anchor = next(iter(self.symbols.values()))
        self.Schedule.On(
            self.DateRules.MonthStart(anchor),
            self.TimeRules.AfterMarketOpen(anchor, 30),
            self.Rebalance,
        )
        self._last_rebalance_date = None

    def Rebalance(self):
        if self.IsWarmingUp or self._last_rebalance_date == self.Time.date():
            return
        self._last_rebalance_date = self.Time.date()
        scores = self.compute_scores()
        if not scores:
            for symbol in self.symbols.values():
                if self.Portfolio[symbol].Invested:
                    self.Liquidate(symbol)
            return
        selected = [symbol for symbol, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:self.top_k]]
        selected_set = set(selected)
        for symbol in self.symbols.values():
            if symbol not in selected_set and self.Portfolio[symbol].Invested:
                self.Liquidate(symbol)
        weight = min(1.0 / self.top_k, self.max_position_weight)
        for symbol in selected:
            self.SetHoldings(symbol, weight)

__ROUTE_METHODS__
