from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class ClassicThirtyStockTop3Momentum(AlphaForgeBaseAlgorithm):
    DEFAULT_UNIVERSE = [
        "MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ASML", "AMD", "ORCL",
        "JPM", "BRK.B", "V", "LLY", "JNJ", "ABBV", "TMO", "WMT", "COST", "PG",
        "KO", "MCD", "CAT", "HON", "UNP", "ETN", "XOM", "LIN", "NEE", "PLD",
    ]

    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def _bool_parameter(self, name, default):
        value = str(self._parameter(name, str(default))).strip().lower()
        return value in {"1", "true", "yes", "on"}

    def _selected_tickers(self):
        raw = str(self._parameter("symbols", ",".join(self.DEFAULT_UNIVERSE)))
        tickers = []
        for ticker in raw.split(","):
            normalized = ticker.strip().upper()
            if normalized and normalized not in tickers:
                tickers.append(normalized)
        unknown = sorted(set(tickers).difference(self.DEFAULT_UNIVERSE))
        if unknown:
            raise ValueError(f"Symbols outside AlphaForge whitelist: {unknown}")
        if not 10 <= len(tickers) <= 30:
            raise ValueError("The selectable stock pool must contain 10 to 30 whitelist symbols")
        return tickers

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2015-01-02"))
        end = datetime.fromisoformat(self._parameter("end_date", "2026-07-17"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.lookback = int(self._parameter("lookback", "126"))
        self.top_k = int(self._parameter("top_k", "3"))
        self.target_gross = float(self._parameter("target_gross", "0.95"))
        self.max_position_weight = float(self._parameter("max_position_weight", "0.35"))
        self.risk_filter_enabled = self._bool_parameter("risk_filter_enabled", True)
        self.risk_sma_period = int(self._parameter("risk_sma_period", "200"))
        tickers = self._selected_tickers()
        if not 1 <= self.top_k <= len(tickers):
            raise ValueError("top_k must be between 1 and the selected stock-pool size")

        self.symbols = []
        for ticker in tickers:
            security = self.add_equity(ticker, Resolution.DAILY)
            security.set_data_normalization_mode(DataNormalizationMode.RAW)
            security.set_leverage(1)
            self.symbols.append(self.af_track_symbol(security.symbol))

        spy = self.add_equity("SPY", Resolution.DAILY)
        spy.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.spy = spy.symbol
        qqq = self.add_equity("QQQ", Resolution.DAILY)
        qqq.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.qqq = qqq.symbol
        self.af_use_security_benchmark(self.spy)
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.settings.free_portfolio_value_percentage = 0.02

        self.momentum = {
            symbol: self.roc(symbol, self.lookback, Resolution.DAILY)
            for symbol in self.symbols
        }
        self.risk_sma = self.sma(self.qqq, self.risk_sma_period, Resolution.DAILY)
        warmup = max(self.lookback + 5, self.risk_sma_period + 5)
        self.set_warm_up(warmup, Resolution.DAILY)
        reference = self.symbols[0]
        self.schedule.on(
            self.date_rules.month_start(reference),
            self.time_rules.after_market_open(reference, 30),
            self.rebalance,
        )

    def on_alpha_data(self, data):
        pass

    def rebalance(self):
        if self.is_warming_up:
            return
        ready_scores = {
            symbol: float(indicator.current.value)
            for symbol, indicator in self.momentum.items()
            if indicator.is_ready and float(self.securities[symbol].price) > 0
        }
        if len(ready_scores) < self.top_k:
            self.af_record_signal(
                "classic_30_insufficient_ready_symbols",
                {
                    "ready_count": len(ready_scores),
                    "required_count": self.top_k,
                },
            )
            return
        if self.risk_filter_enabled and (
            not self.risk_sma.is_ready
            or float(self.securities[self.qqq].price) <= float(self.risk_sma.current.value)
        ):
            self.af_record_signal(
                "classic_30_risk_off",
                {
                    "qqq_price": float(self.securities[self.qqq].price),
                    "qqq_sma": float(self.risk_sma.current.value),
                    "selected": [],
                },
            )
            self.af_liquidate_all("Risk-off: QQQ below SMA")
            return

        scores = ready_scores
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        selected = [symbol for symbol, score in ranked[: self.top_k] if score > 0]
        if not selected:
            self.af_record_signal(
                "classic_30_no_positive_momentum",
                {"scores": {symbol.value: score for symbol, score in ranked}},
            )
            self.af_liquidate_all("Risk-off: no positive momentum")
            return

        per_asset = min(self.max_position_weight, self.target_gross / len(selected))
        target_weights = {symbol: per_asset for symbol in selected}
        self.af_record_signal(
            "classic_30_top3_momentum",
            {
                "scores": {symbol.value: score for symbol, score in ranked},
                "selected": [symbol.value for symbol in selected],
                "target_weight_each": per_asset,
                "risk_filter_enabled": self.risk_filter_enabled,
            },
        )
        self.af_rebalance_to_weights(
            target_weights,
            "Monthly Top-K momentum rebalance",
        )

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_CLASSIC_30_TOP3_MOMENTUM_COMPLETED")
