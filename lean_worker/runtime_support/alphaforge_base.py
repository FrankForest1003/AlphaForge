from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from AlgorithmImports import *


class AlphaForgeBpsFeeModel(FeeModel):
    """Deterministic notional fee model shared by every battle strategy."""

    def __init__(self, fee_bps: float):
        self.fee_rate = max(0.0, float(fee_bps)) / 10_000.0

    def get_order_fee(self, parameters):
        notional = abs(float(parameters.order.quantity) * float(parameters.security.price))
        return OrderFee(CashAmount(notional * self.fee_rate, "USD"))


class AlphaForgeBpsSlippageModel:
    """Simple deterministic price slippage used consistently across candidates."""

    def __init__(self, slippage_bps: float):
        self.slippage_rate = max(0.0, float(slippage_bps)) / 10_000.0

    def get_slippage_approximation(self, asset, order):
        return float(asset.price) * self.slippage_rate


def _number(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _time_text(value: Any) -> str:
    """Serialize Python and .NET date/time values to stable ISO text."""
    if value is None:
        return ""

    # LEAN Python algorithms commonly expose Python datetime/date objects.
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except Exception:
            pass

    # Retain compatibility with .NET DateTime values exposed by Python.NET.
    to_string = getattr(value, "ToString", None)
    if callable(to_string):
        try:
            return str(to_string("o"))
        except Exception:
            try:
                return str(to_string())
            except Exception:
                pass

    return str(value)


def _enum_text(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return repr(value)


def _symbol_key_text(value: Any) -> str:
    """Return a stable ticker key for strings and LEAN Symbol objects."""
    raw = getattr(value, "value", None)
    if raw in (None, ""):
        raw = getattr(value, "Value", None)
    if raw in (None, ""):
        raw = value
    return str(raw).strip().upper()


def af_split_history_frames(history) -> dict[str, Any]:
    """Split a LEAN History DataFrame without mapped-key ``.loc`` access.

    LEAN's PandasMapper raises a Python.NET KeyError when ``history.loc[symbol]``
    is requested for a current ticker that has no rows in the requested period.
    That exception is not reliably caught by a normal Python ``except`` block.
    This helper scans the first MultiIndex level, groups only keys that are
    actually present, and slices by integer positions instead.
    """
    if history is None or bool(getattr(history, "empty", True)):
        return {}
    index = getattr(history, "index", None)
    if index is None or int(getattr(index, "nlevels", 1)) < 2:
        return {}

    level_zero = index.get_level_values(0)
    positions: dict[str, list[int]] = {}
    for position, key in enumerate(level_zero):
        ticker = _symbol_key_text(key)
        if ticker:
            positions.setdefault(ticker, []).append(position)

    frames: dict[str, Any] = {}
    for ticker, row_positions in positions.items():
        frame = history.iloc[row_positions].copy()
        if int(getattr(frame.index, "nlevels", 1)) > 1:
            frame.index = frame.index.droplevel(0)
        frame.columns = [str(column).lower() for column in frame.columns]
        frames[ticker] = frame.sort_index()
    return frames


class AlphaForgeBaseAlgorithm(QCAlgorithm):
    """Base contract for detailed, portable AlphaForge JSON results.

    Subclasses implement:
      - initialize_strategy(self)
      - on_alpha_data(self, data) [optional]
      - on_alpha_order_event(self, order_event) [optional]
      - on_alpha_end(self) [optional]
    """

    def initialize(self):
        self._af_tracked_symbols = []
        self._af_equity_curve = []
        self._af_benchmark_curve = []
        self._af_benchmark_symbol = None
        self._af_benchmark_initial_price = None
        self._af_position_snapshots = []
        self._af_order_events = []
        self._af_orders = {}
        self._af_signals = []
        self._af_ml_training_runs = []
        self._af_ml_predictions = []
        self._af_ml_model_artifacts = []
        self._af_last_daily_snapshot = None
        self._af_pending_target_weights = None
        self._af_pending_rebalance_tag = ""
        self.initialize_strategy()

    def initialize_strategy(self):
        raise NotImplementedError

    def af_track_symbol(self, symbol):
        if symbol not in self._af_tracked_symbols:
            self._af_tracked_symbols.append(symbol)
        return symbol

    def af_configure_security(
        self,
        security,
        *,
        fee_bps: float = 0.0,
        slippage_bps: float = 0.0,
        leverage: float = 1.0,
    ):
        """Apply the immutable ExperimentContract execution assumptions."""
        security.set_data_normalization_mode(DataNormalizationMode.RAW)
        security.set_leverage(float(leverage))
        security.set_fee_model(AlphaForgeBpsFeeModel(fee_bps))
        security.set_slippage_model(AlphaForgeBpsSlippageModel(slippage_bps))
        return security

    def af_set_benchmark_symbol(self, symbol):
        self._af_benchmark_symbol = symbol
        return symbol

    def af_use_security_benchmark(self, symbol):
        """Use an existing security subscription as LEAN and JSON benchmark.

        Passing a Symbol directly to set_benchmark can create an internal Hour
        subscription. AlphaForge distributes Daily data, so a callable benchmark
        reuses the already-added Daily security and avoids requesting hour/spy.zip.
        """
        self.af_set_benchmark_symbol(symbol)

        def benchmark_value(_time):
            price = self.securities[symbol].price
            return price if _number(price) > 0 else 1

        self.set_benchmark(benchmark_value)
        return symbol

    def af_clear_pending_rebalance(self):
        self._af_pending_target_weights = None
        self._af_pending_rebalance_tag = ""

    def af_liquidate_all(self, tag: str):
        """Clear staged targets and liquidate the portfolio."""
        self.af_clear_pending_rebalance()
        self.liquidate(tag=tag)

    def _af_submit_pending_targets(self):
        if self._af_pending_target_weights is None:
            return
        if self.transactions.get_open_orders():
            return

        pending = self._af_pending_target_weights
        tag = self._af_pending_rebalance_tag
        self.af_clear_pending_rebalance()
        targets = [
            PortfolioTarget(symbol, weight)
            for symbol, weight in pending.items()
            if weight > 0
        ]
        if targets:
            self.set_holdings(targets, False)
            self.af_record_signal(
                "staged_rebalance_buy_phase",
                {
                    "tag": tag,
                    "targets": {symbol.value: weight for symbol, weight in pending.items()},
                },
            )

    def af_rebalance_to_weights(self, target_weights, tag: str):
        """Rebalance without requiring sale proceeds before they are filled.

        Daily-resolution market orders placed during market hours are converted
        to Market-On-Close orders. A single batch can therefore fail buying-power
        checks when purchases are evaluated before sale proceeds are available.
        This helper first submits removals/reductions and submits additions only
        after those orders have filled.
        """
        clean = {
            symbol: max(0.0, float(weight))
            for symbol, weight in target_weights.items()
            if float(weight) > 0
        }
        if not clean:
            self.af_liquidate_all(tag)
            return

        self._af_pending_target_weights = clean
        self._af_pending_rebalance_tag = tag
        portfolio_value = _number(self.portfolio.total_portfolio_value)
        reduction_submitted = False
        tolerance = 0.0025
        # SetHoldings applies this reserve before calculating order quantities.
        # Compare against the same effective target; otherwise LEAN may discover
        # small sell orders only inside the final target batch and validate a new
        # buy before those sale proceeds exist.
        free_portfolio_percentage = max(
            0.0,
            min(1.0, _number(self.settings.free_portfolio_value_percentage)),
        )

        for symbol in self._af_tracked_symbols:
            holding = self.portfolio[symbol]
            if not holding.invested:
                continue
            target = clean.get(symbol, 0.0)
            effective_target = target * (1.0 - free_portfolio_percentage)
            current_weight = (
                _number(holding.holdings_value) / portfolio_value
                if portfolio_value > 0
                else 0.0
            )
            if target <= 0:
                self.liquidate(symbol, tag=f"{tag} | phase 1 remove")
                reduction_submitted = True
            elif current_weight > effective_target + tolerance:
                self.set_holdings(symbol, target, tag=f"{tag} | phase 1 reduce")
                reduction_submitted = True

        if not reduction_submitted:
            self._af_submit_pending_targets()

    def af_record_signal(self, name: str, payload: dict[str, Any]):
        self._af_signals.append({"time": _time_text(self.time), "name": name, "payload": payload})

    def af_record_ml_training(self, payload: dict[str, Any]):
        item = dict(payload)
        item.setdefault("time", _time_text(self.time))
        self._af_ml_training_runs.append(item)

    def af_record_ml_prediction(self, payload: dict[str, Any]):
        item = dict(payload)
        item.setdefault("time", _time_text(self.time))
        self._af_ml_predictions.append(item)

    def af_record_model_artifact(self, payload: dict[str, Any]):
        self._af_ml_model_artifacts.append(dict(payload))

    def _af_position_payload(self):
        positions = []
        for symbol in self._af_tracked_symbols:
            holding = self.portfolio[symbol]
            security = self.securities[symbol]
            quantity = _number(holding.quantity)
            if abs(quantity) < 1e-12 and not holding.invested:
                continue
            positions.append({
                "symbol": symbol.value,
                "quantity": quantity,
                "average_price": _number(holding.average_price),
                "market_price": _number(security.price),
                "market_value": _number(holding.holdings_value),
                "holdings_cost": _number(holding.holdings_cost),
                "unrealized_pnl": _number(holding.unrealized_profit),
                "unrealized_pnl_percent": _number(holding.unrealized_profit_percent),
                "weight": 0.0 if not _number(self.portfolio.total_portfolio_value) else _number(holding.holdings_value) / _number(self.portfolio.total_portfolio_value),
                "invested": bool(holding.invested),
            })
        return positions

    def af_capture_snapshot(self, reason: str):
        portfolio_value = _number(self.portfolio.total_portfolio_value)
        cash = _number(self.portfolio.cash)
        holdings_value = _number(self.portfolio.total_holdings_value)
        positions = self._af_position_payload()
        snapshot = {
            "time": _time_text(self.time),
            "reason": reason,
            "portfolio_value": portfolio_value,
            "cash": cash,
            "holdings_value": holdings_value,
            "gross_exposure": 0.0 if not portfolio_value else sum(abs(p["market_value"]) for p in positions) / portfolio_value,
            "net_exposure": 0.0 if not portfolio_value else sum(p["market_value"] for p in positions) / portfolio_value,
            "positions": positions,
        }
        self._af_position_snapshots.append(snapshot)
        self._af_equity_curve.append({
            "time": snapshot["time"],
            "portfolio_value": portfolio_value,
            "cash": cash,
            "holdings_value": holdings_value,
        })
        if self._af_benchmark_symbol is not None:
            benchmark_price = _number(self.securities[self._af_benchmark_symbol].price)
            if benchmark_price > 0:
                if self._af_benchmark_initial_price is None:
                    self._af_benchmark_initial_price = benchmark_price
                normalized = (
                    benchmark_price / self._af_benchmark_initial_price
                    if self._af_benchmark_initial_price
                    else 1.0
                )
                self._af_benchmark_curve.append({
                    "time": snapshot["time"],
                    "symbol": self._af_benchmark_symbol.value,
                    "price": benchmark_price,
                    "normalized_value": normalized,
                    "return": normalized - 1.0,
                })

    def on_data(self, data):
        hook = getattr(self, "on_alpha_data", None)
        if hook:
            hook(data)
        if self.is_warming_up:
            return
        date_key = str(self.time.date())
        if date_key != self._af_last_daily_snapshot:
            self._af_last_daily_snapshot = date_key
            self.af_capture_snapshot("daily")

    def on_order_event(self, order_event):
        order = self.transactions.get_order_by_id(order_event.order_id)
        fee = 0.0
        try:
            fee = _number(order_event.order_fee.value.amount)
        except Exception:
            pass
        event = {
            "time": _time_text(self.time),
            "order_id": int(order_event.order_id),
            "symbol": order_event.symbol.value,
            "status": _enum_text(order_event.status),
            "fill_quantity": _number(order_event.fill_quantity),
            "fill_price": _number(order_event.fill_price),
            "fee": fee,
            "message": str(order_event.message or ""),
            "direction": "buy" if _number(order_event.fill_quantity) > 0 else ("sell" if _number(order_event.fill_quantity) < 0 else "none"),
        }
        self._af_order_events.append(event)
        if order is not None:
            self._af_orders[str(order.id)] = {
                "order_id": int(order.id),
                "time": _time_text(order.time),
                "symbol": order.symbol.value,
                "quantity": _number(order.quantity),
                "type": _enum_text(order.type),
                "status": _enum_text(order.status),
                "tag": str(order.tag or ""),
                "price": _number(order.price),
            }
        if abs(event["fill_quantity"]) > 0:
            self.af_capture_snapshot("fill")
        if self._af_pending_target_weights is not None and not self.transactions.get_open_orders():
            self._af_submit_pending_targets()
        hook = getattr(self, "on_alpha_order_event", None)
        if hook:
            hook(order_event)

    def _af_write_results(self):
        run_dir = Path(os.environ.get("ALPHAFORGE_RUN_DIR", "."))
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "run_id": os.environ.get("ALPHAFORGE_RUN_ID"),
            "equity_curve": self._af_equity_curve,
            "benchmark_curve": self._af_benchmark_curve,
            "position_snapshots": self._af_position_snapshots,
            "orders": list(self._af_orders.values()),
            "order_events": self._af_order_events,
            "signals": self._af_signals,
            "ml": {
                "training_runs": self._af_ml_training_runs,
                "predictions": self._af_ml_predictions,
                "model_artifacts": self._af_ml_model_artifacts,
            },
        }
        (run_dir / "alphaforge_details.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def on_end_of_algorithm(self):
        self.af_capture_snapshot("final")
        hook = getattr(self, "on_alpha_end", None)
        if hook:
            hook()
        self._af_write_results()
