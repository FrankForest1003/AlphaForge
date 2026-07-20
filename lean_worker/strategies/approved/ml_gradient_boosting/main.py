from datetime import datetime
from pathlib import Path
import hashlib
import json
import math
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class MLGradientBoostingStrategy(AlphaForgeBaseAlgorithm):
    FEATURE_NAMES = ["return_5d", "return_21d", "return_63d", "volatility_21d", "sma_gap_63d", "is_msft"]

    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2021-01-04"))
        end = datetime.fromisoformat(self._parameter("end_date", "2025-12-31"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.training_bars = int(self._parameter("training_bars", "420"))
        self.horizon = int(self._parameter("forecast_horizon", "21"))
        self.target_weight = float(self._parameter("target_weight", "0.95"))
        self.random_seed = int(self._parameter("random_seed", "42"))

        self.symbols = []
        for ticker in ["AAPL", "MSFT"]:
            security = self.add_equity(ticker, Resolution.DAILY)
            security.set_data_normalization_mode(DataNormalizationMode.RAW)
            security.set_leverage(1)
            self.symbols.append(self.af_track_symbol(security.symbol))
        spy = self.add_equity("SPY", Resolution.DAILY)
        spy.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.spy = spy.symbol
        self.set_benchmark(lambda time: self.securities[self.spy].price)
        self.af_set_benchmark_symbol(self.spy)

        self.pending_target = None
        self.pending_created_date = None
        self.model = None
        self.set_warm_up(self.training_bars, Resolution.DAILY)
        reference = self.symbols[0]
        self.schedule.on(
            self.date_rules.month_start(reference),
            self.time_rules.after_market_open(reference, 5),
            self.train_predict_rebalance,
        )
        self.schedule.on(
            self.date_rules.every_day(reference),
            self.time_rules.after_market_open(reference, 10),
            self.execute_pending_entry,
        )

    def on_alpha_data(self, data):
        pass

    def _symbol_frame(self, history, symbol):
        try:
            frame = history.loc[symbol]
        except Exception:
            frame = history.xs(symbol, level=0)
        frame = frame.copy()
        frame.columns = [str(c).lower() for c in frame.columns]
        return frame.sort_index()

    def _dataset(self, frame, is_msft):
        close = frame["close"].astype(float)
        daily = close.pct_change()
        features = pd.DataFrame(index=frame.index)
        features["return_5d"] = close.pct_change(5)
        features["return_21d"] = close.pct_change(21)
        features["return_63d"] = close.pct_change(63)
        features["volatility_21d"] = daily.rolling(21).std() * math.sqrt(252)
        features["sma_gap_63d"] = close / close.rolling(63).mean() - 1.0
        features["is_msft"] = float(is_msft)
        target = close.shift(-self.horizon) / close - 1.0
        train = features.copy()
        train["target"] = target
        return features, train.dropna()

    def train_predict_rebalance(self):
        if self.is_warming_up or self.pending_target is not None:
            return
        history = self.history(self.symbols, self.training_bars, Resolution.DAILY)
        if history is None or history.empty:
            self.debug("ML history is empty")
            return
        train_frames = []
        current_rows = {}
        for symbol in self.symbols:
            frame = self._symbol_frame(history, symbol)
            features, train = self._dataset(frame, symbol.value == "MSFT")
            if len(train) < 100 or features.dropna().empty:
                return
            train_frames.append(train)
            current_rows[symbol] = features.dropna().iloc[-1][self.FEATURE_NAMES]
        combined = pd.concat(train_frames, axis=0)
        x_train = combined[self.FEATURE_NAMES].to_numpy(dtype=float)
        y_train = combined["target"].to_numpy(dtype=float)
        self.model = GradientBoostingRegressor(
            random_state=self.random_seed,
            n_estimators=100,
            learning_rate=0.05,
            max_depth=2,
            loss="huber",
        )
        self.model.fit(x_train, y_train)
        predictions = {
            symbol: float(self.model.predict(np.asarray([current_rows[symbol].to_numpy(dtype=float)]))[0])
            for symbol in self.symbols
        }
        winner = max(predictions, key=predictions.get)
        importance = {name: float(value) for name, value in zip(self.FEATURE_NAMES, self.model.feature_importances_)}
        self.af_record_ml_training({
            "model_type": "GradientBoostingRegressor",
            "library": "scikit-learn",
            "training_rows": int(len(combined)),
            "training_bars": self.training_bars,
            "forecast_horizon": self.horizon,
            "random_seed": self.random_seed,
            "feature_names": self.FEATURE_NAMES,
            "feature_importance": importance,
        })
        for rank, (symbol, prediction) in enumerate(sorted(predictions.items(), key=lambda kv: kv[1], reverse=True), 1):
            self.af_record_ml_prediction({
                "symbol": symbol.value,
                "predicted_return": prediction,
                "rank": rank,
                "target_weight": self.target_weight if symbol == winner and prediction > 0 else 0.0,
            })
        self.af_record_signal("ml_monthly_prediction", {
            "predictions": {s.value: p for s, p in predictions.items()},
            "winner": winner.value,
        })

        model_dir = Path(os.environ.get("ALPHAFORGE_MODEL_DIR", "."))
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / "latest_gradient_boosting.joblib"
        joblib.dump(self.model, model_path)
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        self.af_record_model_artifact({"path": str(model_path), "sha256": digest})

        invested = [s for s in self.symbols if self.portfolio[s].invested]
        if predictions[winner] <= 0:
            if invested:
                self.liquidate(tag="ML risk-off: all predictions non-positive")
            return
        if invested == [winner]:
            return
        if invested:
            self.pending_target = winner
            self.pending_created_date = self.time.date()
            self.liquidate(tag="ML phase 1: exit prior winner")
        else:
            self.set_holdings(winner, self.target_weight, tag="ML enter predicted winner")

    def execute_pending_entry(self):
        if self.is_warming_up or self.pending_target is None:
            return
        if self.time.date() <= self.pending_created_date or self.transactions.get_open_orders() or self.portfolio.invested:
            return
        target = self.pending_target
        self.pending_target = None
        self.pending_created_date = None
        self.set_holdings(target, self.target_weight, tag="ML phase 2: enter predicted winner")

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_ML_GRADIENT_BOOSTING_COMPLETED")
