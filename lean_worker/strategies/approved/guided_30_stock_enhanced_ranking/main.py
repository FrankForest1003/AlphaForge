from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm, af_split_history_frames


class GuidedThirtyStockEnhancedRanking(AlphaForgeBaseAlgorithm):
    """Guided Human ranking templates that are distinct from public baselines."""

    DEFAULT_UNIVERSE = [
        "MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ASML", "AMD", "ORCL",
        "JPM", "BRK.B", "V", "LLY", "JNJ", "ABBV", "TMO", "WMT", "COST", "PG",
        "KO", "MCD", "CAT", "HON", "UNP", "ETN", "XOM", "LIN", "NEE", "PLD",
    ]

    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def _bool_parameter(self, name, default):
        return str(self._parameter(name, str(default))).strip().lower() in {
            "1", "true", "yes", "on"
        }

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
        if not 5 <= len(tickers) <= 30:
            raise ValueError("The selectable stock pool must contain 5 to 30 whitelist symbols")
        return tickers

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2016-01-04"))
        end = datetime.fromisoformat(self._parameter("end_date", "2026-06-30"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.signal_mode = str(self._parameter("signal_mode", "multi_horizon"))
        if self.signal_mode not in {"multi_horizon", "risk_adjusted"}:
            raise ValueError("signal_mode must be multi_horizon or risk_adjusted")
        self.lookback = int(self._parameter("lookback", "126"))
        self.top_k = int(self._parameter("top_k", "3"))
        self.target_gross = float(self._parameter("target_gross", "0.95"))
        self.max_position_weight = float(self._parameter("max_position_weight", "0.35"))
        self.risk_filter_enabled = self._bool_parameter("risk_filter_enabled", True)
        self.risk_sma_period = int(self._parameter("risk_sma_period", "200"))
        self.fee_bps = float(self._parameter("transaction_cost_bps", "10"))
        self.slippage_bps = float(self._parameter("slippage_bps", "5"))

        tickers = self._selected_tickers()
        if not 1 <= self.top_k <= len(tickers):
            raise ValueError("top_k must be between 1 and the selected stock-pool size")

        self.symbols = []
        for ticker in tickers:
            security = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                security,
                fee_bps=self.fee_bps,
                slippage_bps=self.slippage_bps,
            )
            self.symbols.append(self.af_track_symbol(security.symbol))

        spy = self.add_equity("SPY", Resolution.DAILY)
        self.af_configure_security(spy)
        self.spy = spy.symbol
        qqq = self.add_equity("QQQ", Resolution.DAILY)
        self.af_configure_security(qqq)
        self.qqq = qqq.symbol
        self.af_use_security_benchmark(self.spy)
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.settings.free_portfolio_value_percentage = 0.02

        self.risk_sma = self.sma(self.qqq, self.risk_sma_period, Resolution.DAILY)
        self.set_warm_up(
            max(self.lookback + 105, self.risk_sma_period + 5),
            Resolution.DAILY,
        )
        reference = self.symbols[0]
        self.schedule.on(
            self.date_rules.month_start(reference),
            self.time_rules.after_market_open(reference, 30),
            self.rebalance,
        )

    def on_alpha_data(self, data):
        pass

    @staticmethod
    def _trailing_return(close, days):
        if len(close) <= days:
            return None
        return float(close.iloc[-1] / close.iloc[-days - 1] - 1.0)

    def _score(self, close):
        short_horizon = max(21, self.lookback // 4)
        medium_horizon = max(short_horizon, self.lookback // 2)
        long_horizon = self.lookback
        short_return = self._trailing_return(close, short_horizon)
        medium_return = self._trailing_return(close, medium_horizon)
        long_return = self._trailing_return(close, long_horizon)
        if any(
            value is None
            for value in (short_return, medium_return, long_return)
        ):
            return None
        if long_return <= 0:
            return None

        trend_window = min(100, len(close))
        trend_average = float(close.tail(trend_window).mean())
        if float(close.iloc[-1]) <= trend_average:
            return None

        blended_momentum = (
            0.25 * short_return
            + 0.35 * medium_return
            + 0.40 * long_return
        )
        if self.signal_mode == "multi_horizon":
            return blended_momentum

        volatility_window = min(63, self.lookback)
        returns = close.pct_change().dropna().tail(volatility_window)
        if len(returns) < max(10, volatility_window // 2):
            return None
        annualized_volatility = float(returns.std() * (252.0 ** 0.5))
        if annualized_volatility <= 0:
            return None
        return blended_momentum / annualized_volatility

    def rebalance(self):
        if self.is_warming_up:
            return
        if self.risk_filter_enabled and (
            not self.risk_sma.is_ready
            or float(self.securities[self.qqq].price) <= float(self.risk_sma.current.value)
        ):
            self.af_record_signal(
                "guided_enhanced_ranking_risk_off",
                {
                    "mode": self.signal_mode,
                    "qqq_price": float(self.securities[self.qqq].price),
                    "qqq_sma": float(self.risk_sma.current.value),
                    "selected": [],
                },
            )
            self.af_liquidate_all("Risk-off: QQQ below SMA")
            return

        history_length = max(self.lookback + 2, 102)
        history = self.history(self.symbols, history_length, Resolution.DAILY)
        frames = af_split_history_frames(history)
        scores = {}
        for symbol in self.symbols:
            frame = frames.get(symbol.value)
            if frame is None or "close" not in frame.columns:
                continue
            score = self._score(frame["close"].astype(float).dropna())
            if score is not None:
                scores[symbol] = score

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        selected = [symbol for symbol, score in ranked[: self.top_k] if score > 0]
        if not selected:
            self.af_record_signal(
                "guided_enhanced_ranking_no_candidates",
                {
                    "mode": self.signal_mode,
                    "scores": {symbol.value: score for symbol, score in ranked},
                },
            )
            self.af_liquidate_all("No positive enhanced-ranking candidates")
            return

        per_asset = min(self.max_position_weight, self.target_gross / len(selected))
        self.af_record_signal(
            "guided_enhanced_ranking",
            {
                "mode": self.signal_mode,
                "scores": {symbol.value: score for symbol, score in ranked},
                "selected": [symbol.value for symbol in selected],
                "target_weight_each": per_asset,
                "lookback": self.lookback,
            },
        )
        self.af_rebalance_to_weights(
            {symbol: per_asset for symbol in selected},
            f"Monthly guided {self.signal_mode} rebalance",
        )

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_GUIDED_30_ENHANCED_RANKING_COMPLETED")
