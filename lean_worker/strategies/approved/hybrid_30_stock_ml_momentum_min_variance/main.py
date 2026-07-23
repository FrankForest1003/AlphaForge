# =============================================================================
# FINAL PRESENTATION STRATEGY — HYBRID ML MOMENTUM + MINIMUM VARIANCE
# =============================================================================
# Purpose:
# Best observed assignment-compliant configuration for the final presentation.
#
# Core methodology:
# 1. A classic momentum and relative-strength score provides the main signal.
# 2. A Gradient Boosting model estimates 21-day stock alpha relative to SPY.
# 3. A QQQ trend filter controls whether the strategy is fully invested or in cash.
# 4. Ledoit-Wolf covariance shrinkage produces more stable minimum-variance weights.
# 5. The final portfolio blends 70% signal weights with 30% minimum-variance weights.
# 6. Risk controls include position stops, cooldown periods, and a portfolio drawdown pause.
#
# Local LEAN validation after execution-safety fixes (2026-07-23):
# - Five-stock run, 2020-01-02 to 2024-12-31: CAGR 27.418%,
#   Sharpe 1.030, maximum drawdown 18.7%, no rejected orders.
# - Full 30-stock compatibility run over the same period completed without
#   rejected orders. These historical results are diagnostics, not guarantees.
#
# =============================================================================
from AlgorithmImports import *
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.covariance import LedoitWolf
from alphaforge_base import AlphaForgeBaseAlgorithm


class HybridThirtyStockMLMomentumMinVariance(AlphaForgeBaseAlgorithm):
    """
    Hybrid machine-learning momentum strategy for QuantConnect.

    The strategy ranks a diversified US stock universe, keeps the strongest
    three candidates, and uses covariance-aware allocation to improve the
    portfolio's risk-adjusted return.
    """

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
        # ---------------------------------------------------------------------
        # 1. Backtest configuration
        # ---------------------------------------------------------------------
        start = datetime.fromisoformat(self._parameter("start_date", "2016-01-04"))
        end = datetime.fromisoformat(self._parameter("end_date", "2026-06-30"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))

        # ---------------------------------------------------------------------
        # 2. Diversified candidate universe
        #    AI/platform leaders are balanced by consumer, healthcare,
        #    financial, energy, and industrial companies.
        # ---------------------------------------------------------------------
        tickers = self._selected_tickers()
        self.symbols = []
        self.fee_bps = float(self._parameter("transaction_cost_bps", "10"))
        self.slippage_bps = float(self._parameter("slippage_bps", "5"))

        # Subscribe to daily adjusted equity data.
        for ticker in tickers:
            equity = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                equity,
                fee_bps=self.fee_bps,
                slippage_bps=self.slippage_bps,
            )
            self.symbols.append(self.af_track_symbol(equity.symbol))
        # The selected benchmark is also used as a broad-market feature.
        benchmark_ticker = str(self._parameter("benchmark", "SPY")).strip().upper()
        spy = self.add_equity(benchmark_ticker, Resolution.DAILY)
        self.af_configure_security(spy)
        self.spy = spy.symbol
        # QQQ is used as the technology-market regime filter.
        qqq = self.add_equity('QQQ', Resolution.DAILY)
        self.af_configure_security(qqq)
        self.qqq = qqq.symbol
        self.af_use_security_benchmark(self.spy)
        self.all_symbols = self.symbols + [self.spy, self.qqq]
        # ---------------------------------------------------------------------
        # 3. Machine-learning configuration
        # ---------------------------------------------------------------------
        # Predict excess return over the next 21 trading days.
        self.forward_horizon = 21
        self.training_window = 504
        self.random_seed = 42
        self.model = GradientBoostingRegressor(loss='huber', n_estimators=60, learning_rate=0.05, max_depth=2, min_samples_leaf=30, subsample=0.75, random_state=self.random_seed)
        self.model_ready = False
        self.feature_names = ['ret_21', 'ret_63', 'ret_126', 'sma_20_gap', 'sma_100_gap', 'macd_gap', 'rsi_14', 'volatility_20', 'spy_ret_21', 'spy_trend']
        # The classic signal remains dominant to reduce ML overfitting.
        self.classic_weight = 0.85
        self.ml_weight = 1.0 - self.classic_weight
        # ---------------------------------------------------------------------
        # 4. Portfolio construction and risk parameters
        # ---------------------------------------------------------------------
        self.number_of_holdings = min(3, len(tickers))
        self.holding_buffer_rank = min(
            len(tickers),
            5,
        )
        self.maximum_total_exposure = 0.95
        self.maximum_stock_weight = 0.35
        self.minimum_weight_change = 0.04
        self.stop_loss = 0.12
        self.cooldown_days = 21
        self.cooldown_until = {}
        self.maximum_portfolio_drawdown = 0.20
        self.risk_filter_enabled = True
        self.pause_days = 60
        self.covariance_loading_factor = 0.000001
        self.score_power_min = 1.25
        self.score_power_max = 1.90
        self.score_dispersion_center = 0.15
        self.score_dispersion_scale = 0.10
        self.transaction_cost_multiplier = 1.0
        # Preserve covariance diversification while letting the stronger
        # cross-sectional signal contribute more than the original 42.5% mix.
        self.signal_allocation_weight = 0.70
        self.minimum_variance_allocation_weight = 0.30
        self.portfolio_peak = float(self.portfolio.total_portfolio_value)
        self.pause_until = None
        # Warm up enough data for the 200-day trend filter and indicators.
        self.set_warm_up(260, Resolution.DAILY)

        # Retrain quarterly and rebalance monthly to limit turnover.
        self.train(self.date_rules.month_start(self.spy), self.time_rules.before_market_open(self.spy, 60), self.quarterly_train)
        self.schedule.on(self.date_rules.month_start(self.spy), self.time_rules.after_market_open(self.spy, 30), self.rebalance)

    # -------------------------------------------------------------------------
    # Feature engineering
    # -------------------------------------------------------------------------
    def build_features(
        self,
        stock_close: pd.Series,
        spy_close: pd.Series
    ) -> pd.DataFrame:
        """
        Build trend, momentum, volatility, RSI, MACD, and market-state features.
        """
        features = pd.DataFrame(index=stock_close.index)
        features['ret_21'] = stock_close.pct_change(21)
        features['ret_63'] = stock_close.pct_change(63)
        features['ret_126'] = stock_close.pct_change(126)
        sma_20 = stock_close.rolling(20).mean()
        sma_100 = stock_close.rolling(100).mean()
        features['sma_20_gap'] = stock_close / sma_20 - 1.0
        features['sma_100_gap'] = stock_close / sma_100 - 1.0
        ema_12 = stock_close.ewm(span=12, adjust=False).mean()
        ema_26 = stock_close.ewm(span=26, adjust=False).mean()
        features['macd_gap'] = ema_12 / ema_26 - 1.0
        price_change = stock_close.diff()
        average_gain = price_change.clip(lower=0).rolling(14).mean()
        average_loss = -price_change.clip(upper=0).rolling(14).mean()
        relative_strength = average_gain / average_loss.replace(0, np.nan)
        rsi = 100.0 - 100.0 / (1.0 + relative_strength)
        features['rsi_14'] = (rsi - 50.0) / 50.0
        features['volatility_20'] = stock_close.pct_change().rolling(20).std() * np.sqrt(252)
        aligned_spy = spy_close.reindex(stock_close.index).ffill()
        features['spy_ret_21'] = aligned_spy.pct_change(21)
        spy_sma_200 = aligned_spy.rolling(200).mean()
        features['spy_trend'] = aligned_spy / spy_sma_200 - 1.0
        return features.replace([np.inf, -np.inf], np.nan)

    # -------------------------------------------------------------------------
    # Model training
    # -------------------------------------------------------------------------
    def quarterly_train(self):
        """Retrain only in January, April, July, and October."""
        quarter_months = [1, 4, 7, 10]
        if self.model_ready and self.time.month not in quarter_months:
            return
        self.train_model()

    def train_model(self):
        """
        Train one pooled Gradient Boosting model across all candidate stocks.

        The target is each stock's future 21-day return minus SPY's return.
        """
        history_length = self.training_window + 230
        history = self.history(self.all_symbols, history_length, Resolution.DAILY)
        if history.empty or 'close' not in history.columns:
            self.debug(f'{self.time.date()}: training skipped because history is unavailable.')
            return
        close = history['close'].unstack(level=0).sort_index()
        if self.spy not in close.columns:
            self.debug(f'{self.time.date()}: SPY is missing from training history.')
            return
        spy_close = close[self.spy].dropna()
        feature_blocks = []
        target_blocks = []
        for symbol in self.symbols:
            if symbol not in close.columns:
                continue
            stock_close = close[symbol].dropna()
            if len(stock_close) < 230:
                continue
            features = self.build_features(stock_close, spy_close)
            stock_forward_return = stock_close.shift(-self.forward_horizon) / stock_close - 1.0
            aligned_spy = spy_close.reindex(stock_close.index).ffill()
            spy_forward_return = aligned_spy.shift(-self.forward_horizon) / aligned_spy - 1.0
            target = stock_forward_return - spy_forward_return
            training_data = features.copy()
            training_data['target'] = target
            training_data = training_data.dropna().tail(self.training_window)
            if len(training_data) < 180:
                continue
            feature_blocks.append(training_data[self.feature_names])
            target_blocks.append(training_data['target'])
        if not feature_blocks:
            self.debug(f'{self.time.date()}: no valid machine-learning samples.')
            return
        x_train = pd.concat(feature_blocks, axis=0)
        y_train = pd.concat(target_blocks, axis=0)
        self.model.fit(x_train.values, y_train.values)
        self.model_ready = True
        self.af_record_ml_training({
            "model_type": "GradientBoostingRegressor",
            "training_rows": int(len(x_train)),
            "training_bars": self.training_window,
            "forecast_horizon": self.forward_horizon,
            "random_seed": self.random_seed,
            "feature_names": self.feature_names,
        })
        self.debug(f'{self.time.date()}: model trained with {len(x_train)} samples.')

    # -------------------------------------------------------------------------
    # Capped allocation helper
    # -------------------------------------------------------------------------
    def allocate_with_cap(
        self,
        raw_weights: pd.Series,
        total_exposure: float,
        maximum_weight: float
    ) -> pd.Series:
        """
        Normalize long-only weights while enforcing a per-stock position cap.
        Any excess weight is redistributed among uncapped positions.
        """
        clean_weights = raw_weights.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0).astype(float)
        final_weights = pd.Series(0.0, index=clean_weights.index, dtype=float)
        if clean_weights.empty or clean_weights.sum() <= 0 or total_exposure <= 0 or (maximum_weight <= 0):
            return final_weights
        feasible_exposure = min(float(total_exposure), float(maximum_weight) * len(clean_weights))
        remaining_symbols = list(clean_weights.index)
        remaining_exposure = feasible_exposure
        while remaining_symbols and remaining_exposure > 1e-10:
            remaining_raw = clean_weights.loc[remaining_symbols]
            if remaining_raw.sum() <= 0:
                break
            proposed = remaining_raw / remaining_raw.sum() * remaining_exposure
            over_cap = proposed[proposed > maximum_weight + 1e-12].index.tolist()
            if not over_cap:
                final_weights.loc[remaining_symbols] = proposed
                break
            for symbol in over_cap:
                final_weights.loc[symbol] = maximum_weight
                remaining_exposure -= maximum_weight
                remaining_symbols.remove(symbol)
            remaining_exposure = max(remaining_exposure, 0.0)
        return final_weights

    # -------------------------------------------------------------------------
    # Monthly portfolio selection and allocation
    # -------------------------------------------------------------------------
    def rebalance(self):
        """
        Select stocks, estimate risk, and place target holdings once per month.
        """
        if self.is_warming_up:
            return
        if self.pause_until is not None and self.time < self.pause_until:
            return
        if not self.model_ready:
            self.train_model()
        if not self.model_ready:
            return
        history = self.history(self.all_symbols, 230, Resolution.DAILY)
        if history.empty or 'close' not in history.columns:
            self.debug(f'{self.time.date()}: rebalance skipped because history is unavailable.')
            return
        close = history['close'].unstack(level=0).sort_index()
        if self.spy not in close.columns:
            return
        spy_close = close[self.spy].dropna()
        if self.qqq not in close.columns:
            return
        qqq_close = close[self.qqq].dropna()
        if len(spy_close) < 200 or len(qqq_close) < 200:
            return
        spy_price = float(spy_close.iloc[-1])
        spy_sma_200 = float(spy_close.rolling(200).mean().iloc[-1])
        qqq_price = float(qqq_close.iloc[-1])
        qqq_sma_50 = float(qqq_close.rolling(50).mean().iloc[-1])
        qqq_sma_200 = float(qqq_close.rolling(200).mean().iloc[-1])
        qqq_volatility_20 = float(qqq_close.pct_change().dropna().tail(20).std() * np.sqrt(252))
        # Move fully to cash when QQQ is below its 200-day moving average.
        if self.risk_filter_enabled and qqq_price <= qqq_sma_200:
            self.af_liquidate_all("Risk-off: QQQ below SMA200")
            self.debug(f'{self.time.date()}: RISK-OFF | QQQ={qqq_price:.2f}, QQQ SMA200={qqq_sma_200:.2f}. Portfolio moved to cash.')
            return
        if qqq_price > qqq_sma_50 and qqq_sma_50 > qqq_sma_200 and (spy_price > spy_sma_200):
            if qqq_volatility_20 < 0.18:
                current_total_exposure = 0.98
                market_regime = 'Strong Calm Technology Uptrend'
            elif qqq_volatility_20 < 0.3:
                current_total_exposure = 0.95
                market_regime = 'Strong Normal Technology Uptrend'
            elif qqq_volatility_20 < 0.45:
                current_total_exposure = 0.85
                market_regime = 'Strong Volatile Technology Uptrend'
            else:
                current_total_exposure = 0.72
                market_regime = 'Strong Extreme-Volatility Technology Uptrend'
        else:
            current_total_exposure = 0.6
            market_regime = 'Weak Technology Uptrend'
        current_total_exposure = min(
            current_total_exposure,
            self.maximum_total_exposure,
        )
        qqq_momentum_63 = float(qqq_close.pct_change(63).iloc[-1])
        qqq_momentum_126 = float(qqq_close.pct_change(126).iloc[-1])
        # Rank eligible stocks by momentum, relative strength, volatility,
        # and the machine-learning alpha estimate.
        candidates = []
        for symbol in self.symbols:
            if symbol not in close.columns:
                continue
            if symbol in self.cooldown_until and self.time < self.cooldown_until[symbol]:
                continue
            stock_close = close[symbol].dropna()
            if len(stock_close) < 200:
                continue
            current_price = float(stock_close.iloc[-1])
            sma_100 = float(stock_close.rolling(100).mean().iloc[-1])
            momentum_63 = float(stock_close.pct_change(63).iloc[-1])
            momentum_126 = float(stock_close.pct_change(126).iloc[-1])
            relative_strength_63 = momentum_63 - qqq_momentum_63
            relative_strength_126 = momentum_126 - qqq_momentum_126
            recent_returns = stock_close.pct_change().dropna().tail(63)
            annual_volatility = float(recent_returns.std() * np.sqrt(252))
            if current_price <= sma_100 or momentum_126 <= 0 or annual_volatility <= 0 or (not np.isfinite(annual_volatility)):
                continue
            classic_score = (0.25 * momentum_63 + 0.35 * momentum_126 + 0.15 * relative_strength_63 + 0.25 * relative_strength_126) / annual_volatility
            features = self.build_features(stock_close, spy_close)
            latest_features = features[self.feature_names].iloc[-1]
            if latest_features.isna().any():
                continue
            predicted_alpha = float(self.model.predict(latest_features.values.reshape(1, -1))[0])
            candidates.append({'symbol': symbol, 'classic_score': classic_score, 'ml_prediction': predicted_alpha, 'volatility': annual_volatility})
        if not candidates:
            self.af_liquidate_all("No stocks passed hybrid selection filters")
            self.debug(f'{self.time.date()}: no stocks passed the selection filters.')
            return
        candidate_frame = pd.DataFrame(candidates).set_index('symbol')
        candidate_frame['classic_rank'] = candidate_frame['classic_score'].rank(pct=True)
        candidate_frame['ml_rank'] = candidate_frame['ml_prediction'].rank(pct=True)
        candidate_frame['combined_score'] = self.classic_weight * candidate_frame['classic_rank'] + self.ml_weight * candidate_frame['ml_rank']
        candidate_frame = candidate_frame.sort_values('combined_score', ascending=False)
        for rank, (symbol, row) in enumerate(candidate_frame.iterrows(), 1):
            self.af_record_ml_prediction({
                "symbol": symbol.value,
                "predicted_alpha": float(row["ml_prediction"]),
                "combined_score": float(row["combined_score"]),
                "rank": rank,
                "selected": rank <= self.number_of_holdings,
            })
        ranked_symbols = list(candidate_frame.index)
        buffer_symbols = set(ranked_symbols[:self.holding_buffer_rank])
        current_holdings = [symbol for symbol in self.symbols if self.portfolio[symbol].invested]
        selected = [symbol for symbol in current_holdings if symbol in buffer_symbols]
        for symbol in ranked_symbols:
            if symbol not in selected:
                selected.append(symbol)
            if len(selected) >= self.number_of_holdings:
                break
        selected = selected[:self.number_of_holdings]
        if not selected:
            self.af_liquidate_all("No stocks passed hybrid selection filters")
            return
        selected_scores_source = (
            candidate_frame['combined_score']
            .reindex(selected)
            .astype(float)
        )
        selected_volatility_source = (
            candidate_frame['volatility']
            .reindex(selected)
            .astype(float)
        )

        selected_scores = pd.Series(
            selected_scores_source.to_numpy(dtype=float),
            index=selected,
            dtype=float
        ).clip(lower=0.05)

        selected_volatility = pd.Series(
            selected_volatility_source.to_numpy(dtype=float),
            index=selected,
            dtype=float
        ).clip(lower=0.01)

        ranked_score_values = np.sort(
            selected_scores.to_numpy(dtype=float)
        )[::-1]

        if len(ranked_score_values) >= 3:
            score_gap = float(
                ranked_score_values[0] - ranked_score_values[2]
            )
        elif len(ranked_score_values) >= 2:
            score_gap = float(
                ranked_score_values[0] - ranked_score_values[-1]
            )
        else:
            score_gap = 0.0

        dispersion_scale = max(self.score_dispersion_scale, np.finfo(float).eps)
        scaled_dispersion = (score_gap - self.score_dispersion_center) / dispersion_scale
        score_power = self.score_power_min + (
            self.score_power_max - self.score_power_min
        ) * 0.5 * (1.0 + np.tanh(scaled_dispersion))

        raw_weights = pd.Series(
            np.power(
                selected_scores.to_numpy(dtype=float),
                score_power
            )
            / selected_volatility.to_numpy(dtype=float),
            index=selected,
            dtype=float
        )
        score_weights = self.allocate_with_cap(
            raw_weights=raw_weights,
            total_exposure=current_total_exposure,
            maximum_weight=self.maximum_stock_weight
        )

        # Estimate covariance from the selected stocks only.
        # Ledoit-Wolf shrinkage is more stable than the raw sample covariance.
        selected_returns = (
            close[selected]
            .pct_change()
            .dropna()
            .tail(63)
        )

        min_variance_weights = score_weights.copy()

        if len(selected_returns) >= 60:
            covariance = LedoitWolf().fit(
                selected_returns.values
            ).covariance_ * 252
            diagonal = np.diag(covariance).copy()
            loading = self.covariance_loading_factor * np.maximum(
                diagonal,
                np.finfo(float).eps,
            )
            covariance = covariance + np.diag(loading)
            precision = np.linalg.pinv(covariance)
            ones = np.ones(len(selected))
            minimum_variance_raw = precision @ ones
            minimum_variance_raw = np.clip(
                minimum_variance_raw,
                0.0,
                None
            )

            if minimum_variance_raw.sum() > 0:
                minimum_variance_raw = pd.Series(
                    minimum_variance_raw,
                    index=selected
                )

                min_variance_weights = self.allocate_with_cap(
                    raw_weights=minimum_variance_raw,
                    total_exposure=current_total_exposure,
                    maximum_weight=self.maximum_stock_weight
                )

        # Blend expected-return information with covariance-aware risk control.
        target_weights = (
            self.signal_allocation_weight * score_weights
            + self.minimum_variance_allocation_weight * min_variance_weights
        )
        portfolio_value = float(self.portfolio.total_portfolio_value)
        desired_weights = {symbol: float(target_weights[symbol]) for symbol in selected}
        current_holdings = [symbol for symbol in self.symbols if self.portfolio[symbol].invested]
        candidate_predictions = candidate_frame['ml_prediction'].to_dict()
        execution_weights = {}
        transaction_cost_rate = (
            (self.fee_bps + self.slippage_bps) / 10000.0
            * self.transaction_cost_multiplier
        )
        execution_symbols = selected + [
            symbol for symbol in current_holdings if symbol not in selected
        ]
        for symbol in execution_symbols:
            target_weight = desired_weights.get(symbol, 0.0)
            current_weight = float(self.portfolio[symbol].holdings_value) / portfolio_value if portfolio_value > 0 else 0.0
            # A dropped holding must exit. Applying the edge/cost filter to it
            # used to preserve stale positions and could push gross exposure
            # above 100% when the new selections were added.
            if symbol not in selected:
                execution_weights[symbol] = 0.0
                continue
            weight_difference = abs(target_weight - current_weight)
            expected_edge = abs(float(candidate_predictions.get(symbol, 0.0)))
            expected_utility_gain = weight_difference * expected_edge
            estimated_transaction_cost = weight_difference * transaction_cost_rate
            if weight_difference < self.minimum_weight_change or expected_utility_gain <= estimated_transaction_cost:
                execution_weights[symbol] = current_weight
                continue
            dampening = min(
                1.0,
                max(0.0, (expected_edge - transaction_cost_rate) / expected_edge),
            )
            execution_weights[symbol] = current_weight + dampening * (target_weight - current_weight)
        execution_gross = sum(
            max(0.0, float(weight))
            for weight in execution_weights.values()
        )
        execution_cap = min(
            current_total_exposure,
            self.maximum_total_exposure,
        )
        if execution_gross > execution_cap and execution_gross > 0:
            scale = execution_cap / execution_gross
            execution_weights = {
                symbol: max(0.0, float(weight)) * scale
                for symbol, weight in execution_weights.items()
            }
        self.af_rebalance_to_weights(
            execution_weights,
            "Monthly hybrid ML momentum and minimum-variance rebalance",
        )
        details = []
        for symbol in selected:
            details.append(f"{symbol}: weight={target_weights[symbol]:.1%}, classic={candidate_frame.loc[symbol, 'classic_score']:.2f}, ML={candidate_frame.loc[symbol, 'ml_prediction']:.2%}")
        self.debug(f'{self.time.date()}: Regime={market_regime}, Gap={score_gap:.2f}, Power={score_power:.2f}, Exposure={current_total_exposure:.0%} | ' + ' | '.join(details))

    # -------------------------------------------------------------------------
    # Daily risk monitoring
    # -------------------------------------------------------------------------
    def on_alpha_data(self, data):
        """
        Enforce portfolio-level drawdown control and per-position stop losses.
        """
        if self.is_warming_up:
            return
        portfolio_value = float(self.portfolio.total_portfolio_value)
        if self.pause_until is not None:
            if self.time < self.pause_until:
                return
            self.debug(f'{self.time.date()}: portfolio pause completed; strategy may resume trading.')
            self.pause_until = None
            self.portfolio_peak = portfolio_value
            self.rebalance()
            return
        self.portfolio_peak = max(self.portfolio_peak, portfolio_value)
        portfolio_drawdown = 1.0 - portfolio_value / self.portfolio_peak if self.portfolio_peak > 0 else 0.0
        if portfolio_drawdown >= self.maximum_portfolio_drawdown:
            self.af_liquidate_all("Portfolio drawdown pause")
            self.pause_until = self.time + timedelta(days=self.pause_days)
            self.portfolio_peak = portfolio_value
            self.debug(f'{self.time.date()}: portfolio drawdown reached {portfolio_drawdown:.2%}. All positions were liquidated. Trading paused until {self.pause_until.date()}.')
            return
        stopped_symbols = []
        for symbol in self.symbols:
            holding = self.portfolio[symbol]
            if not holding.invested:
                continue
            current_price = float(self.securities[symbol].price)
            average_price = float(holding.average_price)
            if current_price <= 0 or average_price <= 0:
                continue
            position_return = current_price / average_price - 1.0
            if position_return <= -self.stop_loss:
                stopped_symbols.append(symbol)
                self.cooldown_until[symbol] = self.time + timedelta(days=self.cooldown_days)
                self.debug(f'{self.time.date()}: {symbol} stop loss triggered. Return={position_return:.2%}. Cooldown until {self.cooldown_until[symbol].date()}.')
        if stopped_symbols:
            stopped_set = set(stopped_symbols)
            remaining_weights = {
                other: max(
                    0.0,
                    float(self.portfolio[other].holdings_value) / portfolio_value,
                )
                for other in self.symbols
                if other not in stopped_set and self.portfolio[other].invested
            }
            names = ",".join(symbol.value for symbol in stopped_symbols)
            self.af_rebalance_to_weights(
                remaining_weights,
                f"Stop-loss exit: {names}",
            )

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_HYBRID_30_ML_MOMENTUM_MIN_VARIANCE_COMPLETED")
