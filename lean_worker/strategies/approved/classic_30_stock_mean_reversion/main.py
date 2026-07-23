from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class ClassicThirtyStockMeanReversion(AlphaForgeBaseAlgorithm):
    """Monthly cross-sectional mean reversion with a shared market risk gate."""

    DEFAULT_UNIVERSE = [
        "MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ASML", "AMD", "ORCL",
        "JPM", "BRK.B", "V", "LLY", "JNJ", "ABBV", "TMO", "WMT", "COST", "PG",
        "KO", "MCD", "CAT", "HON", "UNP", "ETN", "XOM", "LIN", "NEE", "PLD",
    ]

    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

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
        if not tickers:
            raise ValueError("Select at least one stock")
        return tickers

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2016-01-04"))
        end = datetime.fromisoformat(self._parameter("end_date", "2026-06-30"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.lookback = 21
        self.top_k = 3
        self.target_gross = 0.95
        self.max_position_weight = 0.35
        self.risk_filter_enabled = True
        self.risk_sma_period = 200
        self.fee_bps = float(self._parameter("transaction_cost_bps", "10"))
        self.slippage_bps = float(self._parameter("slippage_bps", "5"))
        tickers = self._selected_tickers()
        self.top_k = min(3, len(tickers))

        self.symbols = []
        for ticker in tickers:
            security = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                security,
                fee_bps=self.fee_bps,
                slippage_bps=self.slippage_bps,
            )
            self.symbols.append(self.af_track_symbol(security.symbol))

        benchmark_ticker = str(self._parameter("benchmark", "SPY")).strip().upper()
        spy = self.add_equity(benchmark_ticker, Resolution.DAILY)
        self.af_configure_security(spy)
        self.spy = spy.symbol
        qqq = self.add_equity("QQQ", Resolution.DAILY)
        self.af_configure_security(qqq)
        self.qqq = qqq.symbol
        self.af_use_security_benchmark(self.spy)
        self.settings.minimum_order_margin_portfolio_percentage = 0

        self.reversion = {
            symbol: self.roc(symbol, self.lookback, Resolution.DAILY)
            for symbol in self.symbols
        }
        self.risk_sma = self.sma(self.qqq, self.risk_sma_period, Resolution.DAILY)
        self.set_warm_up(max(self.lookback + 5, self.risk_sma_period + 5), Resolution.DAILY)
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
        if self.risk_filter_enabled and (
            not self.risk_sma.is_ready
            or float(self.securities[self.qqq].price) <= float(self.risk_sma.current.value)
        ):
            self.af_record_signal(
                "mean_reversion_risk_off",
                {
                    "qqq_price": float(self.securities[self.qqq].price),
                    "qqq_sma": float(self.risk_sma.current.value),
                    "selected": [],
                },
            )
            self.af_liquidate_all("Risk-off: QQQ below SMA")
            return

        scores = {
            symbol: float(indicator.current.value)
            for symbol, indicator in self.reversion.items()
            if indicator.is_ready and float(self.securities[symbol].price) > 0
        }
        ranked = sorted(scores.items(), key=lambda item: item[1])
        selected = [symbol for symbol, score in ranked[: self.top_k] if score < 0]
        if not selected:
            self.af_record_signal(
                "mean_reversion_no_oversold_assets",
                {"returns": {symbol.value: score for symbol, score in ranked}},
            )
            self.af_liquidate_all("No negative-return mean-reversion candidates")
            return

        per_asset = min(self.max_position_weight, self.target_gross / len(selected))
        self.af_record_signal(
            "classic_30_mean_reversion",
            {
                "returns": {symbol.value: score for symbol, score in ranked},
                "selected": [symbol.value for symbol in selected],
                "target_weight_each": per_asset,
                "lookback": self.lookback,
            },
        )
        self.af_rebalance_to_weights(
            {symbol: per_asset for symbol in selected},
            "Monthly cross-sectional mean-reversion rebalance",
        )

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_CLASSIC_30_MEAN_REVERSION_COMPLETED")
