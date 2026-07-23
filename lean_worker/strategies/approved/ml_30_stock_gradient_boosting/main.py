from datetime import datetime
from pathlib import Path
import hashlib
import math
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm, af_split_history_frames


class MLThirtyStockGradientBoosting(AlphaForgeBaseAlgorithm):
    DEFAULT_UNIVERSE = [
        "MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ASML", "AMD", "ORCL",
        "JPM", "BRK.B", "V", "LLY", "JNJ", "ABBV", "TMO", "WMT", "COST", "PG",
        "KO", "MCD", "CAT", "HON", "UNP", "ETN", "XOM", "LIN", "NEE", "PLD",
    ]
    FEATURE_NAMES = [
        "return_5d",
        "return_21d",
        "return_63d",
        "return_126d",
        "volatility_21d",
        "sma_gap_63d",
        "relative_return_21d",
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
        end = datetime.fromisoformat(self._parameter("end_date", "2026-07-17"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.training_bars = 420
        self.horizon = 21
        self.top_k = 3
        self.target_gross = 0.95
        self.max_position_weight = 0.35
        self.random_seed = 42
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
        self.risk_sma = self.sma(self.qqq, self.risk_sma_period, Resolution.DAILY)

        self.model = None
        self.set_warm_up(max(self.training_bars, self.risk_sma_period + 5), Resolution.DAILY)
        reference = self.symbols[0]
        self.schedule.on(
            self.date_rules.month_start(reference),
            self.time_rules.after_market_open(reference, 30),
            self.train_predict_rebalance,
        )

    def on_alpha_data(self, data):
        pass

    def _dataset(self, frame, spy_close):
        close = frame["close"].astype(float)
        spy_aligned = spy_close.reindex(close.index).ffill()
        daily = close.pct_change()
        features = pd.DataFrame(index=frame.index)
        features["return_5d"] = close.pct_change(5)
        features["return_21d"] = close.pct_change(21)
        features["return_63d"] = close.pct_change(63)
        features["return_126d"] = close.pct_change(126)
        features["volatility_21d"] = daily.rolling(21).std() * math.sqrt(252)
        features["sma_gap_63d"] = close / close.rolling(63).mean() - 1.0
        features["relative_return_21d"] = close.pct_change(21) - spy_aligned.pct_change(21)
        target = close.shift(-self.horizon) / close - 1.0
        train = features.copy()
        train["target"] = target
        return features, train.dropna()

    def train_predict_rebalance(self):
        if self.is_warming_up:
            return
        if self.risk_filter_enabled and (
            not self.risk_sma.is_ready
            or float(self.securities[self.qqq].price) <= float(self.risk_sma.current.value)
        ):
            self.af_record_signal(
                "ml_30_risk_off",
                {
                    "qqq_price": float(self.securities[self.qqq].price),
                    "qqq_sma": float(self.risk_sma.current.value),
                    "selected": [],
                },
            )
            self.af_liquidate_all("Risk-off: QQQ below SMA")
            return

        history_symbols = list(self.symbols) + [self.spy]
        history = self.history(history_symbols, self.training_bars, Resolution.DAILY)
        if history is None or history.empty:
            self.debug("ML history is empty")
            return
        history_frames = af_split_history_frames(history)
        spy_frame = history_frames.get(self.spy.value.upper())
        if spy_frame is None or spy_frame.empty or "close" not in spy_frame.columns:
            self.af_record_signal(
                "ml_30_missing_spy_history",
                {"available_symbols": sorted(history_frames)},
            )
            self.debug("ML SPY history is unavailable for the requested window")
            return
        spy_close = spy_frame["close"].astype(float)
        train_frames = []
        current_rows = {}
        skipped_symbols = []
        for symbol in self.symbols:
            frame = history_frames.get(symbol.value.upper())
            if frame is None or frame.empty:
                skipped_symbols.append({
                    "symbol": symbol.value,
                    "reason": "history_not_available_in_requested_window",
                })
                continue
            try:
                features, train = self._dataset(frame, spy_close)
                current = features.dropna()
            except Exception as exc:
                skipped_symbols.append({"symbol": symbol.value, "reason": str(exc)})
                continue
            if len(train) < 100 or current.empty:
                skipped_symbols.append({
                    "symbol": symbol.value,
                    "reason": "insufficient_history",
                    "training_rows": int(len(train)),
                })
                continue
            tagged = train.copy()
            tagged["symbol"] = symbol.value
            train_frames.append(tagged)
            current_rows[symbol] = current.iloc[-1][self.FEATURE_NAMES]

        if len(current_rows) < self.top_k or not train_frames:
            self.af_record_signal(
                "ml_30_insufficient_eligible_symbols",
                {
                    "eligible_count": len(current_rows),
                    "required_count": self.top_k,
                    "skipped_symbols": skipped_symbols,
                },
            )
            return

        combined = pd.concat(train_frames, axis=0)
        x_train = combined[self.FEATURE_NAMES].to_numpy(dtype=float)
        y_train = combined["target"].to_numpy(dtype=float)
        self.model = GradientBoostingRegressor(
            random_state=self.random_seed,
            n_estimators=150,
            learning_rate=0.04,
            max_depth=2,
            min_samples_leaf=20,
            loss="huber",
        )
        self.model.fit(x_train, y_train)
        predictions = {
            symbol: float(
                self.model.predict(
                    np.asarray([current_rows[symbol].to_numpy(dtype=float)])
                )[0]
            )
            for symbol in current_rows
        }
        ranked = sorted(predictions.items(), key=lambda item: item[1], reverse=True)
        selected = [symbol for symbol, prediction in ranked[: self.top_k] if prediction > 0]
        importance = {
            name: float(value)
            for name, value in zip(self.FEATURE_NAMES, self.model.feature_importances_)
        }
        self.af_record_ml_training(
            {
                "model_type": "GradientBoostingRegressor",
                "library": "scikit-learn",
                "training_rows": int(len(combined)),
                "training_bars": self.training_bars,
                "forecast_horizon": self.horizon,
                "random_seed": self.random_seed,
                "feature_names": self.FEATURE_NAMES,
                "feature_importance": importance,
                "configured_universe_size": len(self.symbols),
                "eligible_universe_size": len(current_rows),
                "skipped_symbols": skipped_symbols,
            }
        )
        per_asset = (
            min(self.max_position_weight, self.target_gross / len(selected))
            if selected
            else 0.0
        )
        for rank, (symbol, prediction) in enumerate(ranked, 1):
            self.af_record_ml_prediction(
                {
                    "symbol": symbol.value,
                    "predicted_return": prediction,
                    "rank": rank,
                    "selected": symbol in selected,
                    "target_weight": per_asset if symbol in selected else 0.0,
                }
            )
        self.af_record_signal(
            "ml_30_monthly_prediction",
            {
                "predictions": {symbol.value: value for symbol, value in ranked},
                "selected": [symbol.value for symbol in selected],
                "target_weight_each": per_asset,
            },
        )

        model_dir = Path(os.environ.get("ALPHAFORGE_MODEL_DIR", "."))
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / "latest_gradient_boosting_30_stock.joblib"
        joblib.dump(self.model, model_path)
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        self.af_record_model_artifact(
            {
                "path": str(model_path),
                "sha256": digest,
                "model_type": "GradientBoostingRegressor",
                "saved_at": str(self.time),
            }
        )

        if not selected:
            self.af_liquidate_all("ML risk-off: no positive predictions")
            return
        target_weights = {symbol: per_asset for symbol in selected}
        self.af_rebalance_to_weights(
            target_weights,
            "Monthly ML Top-K rebalance",
        )

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_ML_30_GRADIENT_BOOSTING_COMPLETED")
