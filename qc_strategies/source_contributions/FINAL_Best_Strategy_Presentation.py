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
# 5. The final portfolio blends 42.5% signal weights with 57.5% minimum-variance weights.
# 6. Risk controls include position stops, cooldown periods, and a portfolio drawdown pause.
#
# Reported QuantConnect result for this configuration:
# - Backtest period: 2020-07-01 to 2026-07-10
# - CAGR: 29.081%
# - Sharpe Ratio: 1.088
# - Sortino Ratio: 1.220
# - Maximum Drawdown: 18.6%
# - Alpha: 0.127
# - Information Ratio: 0.550
#
# =============================================================================
from AlgorithmImports import *
from datetime import timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.covariance import LedoitWolf

class BufferedMLMomentumStrategy(QCAlgorithm):
    """
    Hybrid machine-learning momentum strategy for QuantConnect.

    The strategy ranks a diversified US stock universe, keeps the strongest
    three candidates, and uses covariance-aware allocation to improve the
    portfolio's risk-adjusted return.
    """

    def initialize(self):
        # ---------------------------------------------------------------------
        # 1. Backtest configuration
        # ---------------------------------------------------------------------
        self.set_start_date(2020, 7, 1)
        self.set_end_date(2026, 7, 10)
        self.set_cash(100000)

        # ---------------------------------------------------------------------
        # 2. Diversified candidate universe
        #    AI/platform leaders are balanced by consumer, healthcare,
        #    financial, energy, and industrial companies.
        # ---------------------------------------------------------------------
        tickers = ['NVDA', 'AVGO', 'MSFT', 'GOOGL', 'META', 'COST', 'LLY', 'JPM', 'XOM', 'CAT']
        self.symbols = []

        # Subscribe to daily adjusted equity data.
        for ticker in tickers:
            equity = self.add_equity(ticker, Resolution.DAILY)
            self.symbols.append(equity.symbol)
        # SPY is the performance benchmark and a broad-market feature.
        self.spy = self.add_equity('SPY', Resolution.DAILY).symbol
        # QQQ is used as the technology-market regime filter.
        self.qqq = self.add_equity('QQQ', Resolution.DAILY).symbol
        self.set_benchmark(self.spy)
        self.all_symbols = self.symbols + [self.spy, self.qqq]
        self.settings.free_portfolio_value_percentage = 0.02
        # ---------------------------------------------------------------------
        # 3. Machine-learning configuration
        # ---------------------------------------------------------------------
        # Predict excess return over the next 21 trading days.
        self.forward_horizon = 21
        self.training_window = 504
        self.model = GradientBoostingRegressor(loss='huber', n_estimators=60, learning_rate=0.05, max_depth=2, min_samples_leaf=30, subsample=0.75, random_state=42)
        self.model_ready = False
        self.feature_names = ['ret_21', 'ret_63', 'ret_126', 'sma_20_gap', 'sma_100_gap', 'macd_gap', 'rsi_14', 'volatility_20', 'spy_ret_21', 'spy_trend']
        # The classic signal remains dominant to reduce ML overfitting.
        self.classic_weight = 0.85
        self.ml_weight = 0.15
        # ---------------------------------------------------------------------
        # 4. Portfolio construction and risk parameters
        # ---------------------------------------------------------------------
        self.number_of_holdings = 3
        self.holding_buffer_rank = 5
        self.maximum_total_exposure = 0.9
        self.maximum_stock_weight = 0.35
        self.minimum_weight_change = 0.04
        self.stop_loss = 0.12
        self.cooldown_days = 21
        self.cooldown_until = {}
        self.maximum_portfolio_drawdown = 0.2
        self.pause_days = 60
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
        if qqq_price <= qqq_sma_200:
            self.liquidate()
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
            self.liquidate()
            self.debug(f'{self.time.date()}: no stocks passed the selection filters.')
            return
        candidate_frame = pd.DataFrame(candidates).set_index('symbol')
        candidate_frame['classic_rank'] = candidate_frame['classic_score'].rank(pct=True)
        candidate_frame['ml_rank'] = candidate_frame['ml_prediction'].rank(pct=True)
        candidate_frame['combined_score'] = self.classic_weight * candidate_frame['classic_rank'] + self.ml_weight * candidate_frame['ml_rank']
        candidate_frame = candidate_frame.sort_values('combined_score', ascending=False)
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
            self.liquidate()
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

        if score_gap >= 0.3:
            score_power = 1.9
        elif score_gap >= 0.15:
            score_power = 1.6
        else:
            score_power = 1.25

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
            0.425 * score_weights
            + 0.575 * min_variance_weights
        )
        for symbol in self.symbols:
            if self.portfolio[symbol].invested and symbol not in selected:
                self.liquidate(symbol)
        portfolio_value = float(self.portfolio.total_portfolio_value)
        for symbol in selected:
            target_weight = float(target_weights[symbol])
            current_weight = float(self.portfolio[symbol].holdings_value) / portfolio_value if portfolio_value > 0 else 0.0
            weight_difference = abs(target_weight - current_weight)
            if not self.portfolio[symbol].invested or weight_difference >= self.minimum_weight_change:
                self.set_holdings(symbol, target_weight)
        details = []
        for symbol in selected:
            details.append(f"{symbol}: weight={target_weights[symbol]:.1%}, classic={candidate_frame.loc[symbol, 'classic_score']:.2f}, ML={candidate_frame.loc[symbol, 'ml_prediction']:.2%}")
        self.debug(f'{self.time.date()}: Regime={market_regime}, Gap={score_gap:.2f}, Power={score_power:.2f}, Exposure={current_total_exposure:.0%} | ' + ' | '.join(details))

    # -------------------------------------------------------------------------
    # Daily risk monitoring
    # -------------------------------------------------------------------------
    def on_data(self, data):
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
            self.liquidate()
            self.pause_until = self.time + timedelta(days=self.pause_days)
            self.portfolio_peak = portfolio_value
            self.debug(f'{self.time.date()}: portfolio drawdown reached {portfolio_drawdown:.2%}. All positions were liquidated. Trading paused until {self.pause_until.date()}.')
            return
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
                self.liquidate(symbol)
                self.cooldown_until[symbol] = self.time + timedelta(days=self.cooldown_days)
                self.debug(f'{self.time.date()}: {symbol} stop loss triggered. Return={position_return:.2%}. Cooldown until {self.cooldown_until[symbol].date()}.')
