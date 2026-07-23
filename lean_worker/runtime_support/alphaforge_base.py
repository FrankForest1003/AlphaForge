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
        self.settings.free_portfolio_value_percentage = 0.02
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
        self._af_rebalance_state = None
        self._af_rebalance_events = []
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
        """Apply the shared market and execution settings for this run."""
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
        self._af_rebalance_state = None

    def af_liquidate_all(self, tag: str):
        """Clear staged targets and liquidate the portfolio."""
        self.af_clear_pending_rebalance()
        self.liquidate(tag=tag)

    def _af_record_rebalance_event(self, name: str, payload: dict[str, Any]):
        item = {
            "time": _time_text(self.time),
            "name": name,
            "payload": payload,
        }
        self._af_rebalance_events.append(item)
        self.af_record_signal(name, payload)

    @staticmethod
    def _af_order_status_text(status: Any) -> str:
        return _enum_text(status).strip().lower().split(".")[-1]

    @classmethod
    def _af_order_status_closed(cls, status: Any) -> bool:
        return cls._af_order_status_text(status) in {
            "filled",
            "canceled",
            "cancelled",
            "invalid",
        }

    @classmethod
    def _af_order_status_failed(cls, status: Any) -> bool:
        return cls._af_order_status_text(status) in {
            "canceled",
            "cancelled",
            "invalid",
        }

    def _af_register_rebalance_ticket(self, ticket, *, purpose: str, symbol):
        if ticket is None or self._af_rebalance_state is None:
            return
        order_id = int(ticket.order_id)
        self._af_rebalance_state["active_order_ids"].add(order_id)
        self._af_rebalance_state["orders"][order_id] = {
            "purpose": purpose,
            "symbol": symbol,
            "ticket": ticket,
        }

    def _af_submit_opening_orders(self):
        """Liquidate assets that are absent from the new target portfolio."""
        state = self._af_rebalance_state
        if state is None:
            return
        state["phase"] = "opening_removals"
        tag = state["tag"]
        targets = state["targets"]

        for symbol in self._af_tracked_symbols:
            holding = self.portfolio[symbol]
            quantity = _number(holding.quantity)
            if symbol not in targets and quantity > 0:
                ticket = self.market_on_open_order(
                    symbol,
                    -quantity,
                    tag=f"{tag} | opening remove",
                )
                self._af_register_rebalance_ticket(
                    ticket,
                    purpose="remove",
                    symbol=symbol,
                )

        self._af_record_rebalance_event(
            "staged_rebalance_removal_phase",
            {
                "tag": tag,
                "targets": {
                    symbol.value: weight for symbol, weight in targets.items()
                },
                "order_ids": sorted(state["active_order_ids"]),
            },
        )
        if not state["active_order_ids"]:
            state["phase"] = "await_sizing_bar"

    def _af_target_deltas(self) -> dict[Any, int]:
        state = self._af_rebalance_state
        if state is None:
            return {}
        portfolio_value = _number(self.portfolio.total_portfolio_value)
        if portfolio_value <= 0:
            return {}

        deltas = {}
        for symbol, weight in state["targets"].items():
            price = _number(self.securities[symbol].price)
            if price <= 0:
                continue
            current_weight = (
                _number(self.portfolio[symbol].holdings_value) / portfolio_value
            )
            tolerance = max(0.0025, price / portfolio_value)
            if abs(current_weight - weight) <= tolerance:
                continue
            desired_quantity = int((portfolio_value * weight) // price)
            current_quantity = int(_number(self.portfolio[symbol].quantity))
            delta = desired_quantity - current_quantity
            if delta:
                deltas[symbol] = delta
        return deltas

    def _af_submit_adjustment_phase(self, *, reductions: bool):
        state = self._af_rebalance_state
        if state is None:
            return
        state["phase"] = "adjust_reductions" if reductions else "adjust_buys"
        state["active_order_ids"] = set()
        deltas = self._af_target_deltas()
        selected = {
            symbol: quantity
            for symbol, quantity in deltas.items()
            if (quantity < 0 if reductions else quantity > 0)
        }
        for symbol, quantity in selected.items():
            if reductions:
                ticket = self.market_on_open_order(
                    symbol,
                    quantity,
                    tag=f"{state['tag']} | {state['phase']}",
                )
            else:
                portfolio_value = _number(self.portfolio.total_portfolio_value)
                current_quantity = int(_number(self.portfolio[symbol].quantity))
                desired_quantity = current_quantity + quantity
                target_value = portfolio_value * state["targets"][symbol]
                limit_price = target_value / desired_quantity
                ticket = self.limit_order(
                    symbol,
                    quantity,
                    limit_price,
                    tag=f"{state['tag']} | {state['phase']}",
                )
            self._af_register_rebalance_ticket(
                ticket,
                purpose=state["phase"],
                symbol=symbol,
            )

        self._af_record_rebalance_event(
            f"staged_rebalance_{state['phase']}",
            {
                "tag": state["tag"],
                "deltas": {symbol.value: value for symbol, value in selected.items()},
                "order_ids": sorted(state["active_order_ids"]),
                "sizing_date": state.get("sizing_date"),
            },
        )
        if not state["active_order_ids"]:
            if reductions:
                self._af_submit_adjustment_phase(reductions=False)
            else:
                self._af_complete_rebalance()
        else:
            state["phase_submitted_date"] = str(self.time.date())

    def _af_complete_rebalance(self):
        state = self._af_rebalance_state
        if state is None:
            return
        targets = state["targets"]
        tag = state["tag"]
        portfolio_value = _number(self.portfolio.total_portfolio_value)
        actual_weights = {}
        outside_targets = []
        for symbol in self._af_tracked_symbols:
            holding = self.portfolio[symbol]
            if holding.invested and portfolio_value > 0:
                actual_weights[symbol.value] = (
                    _number(holding.holdings_value) / portfolio_value
                )
                if symbol not in targets:
                    outside_targets.append(symbol.value)

        deviations = {}
        for symbol, target in targets.items():
            actual = actual_weights.get(symbol.value, 0.0)
            share_tolerance = (
                _number(self.securities[symbol].price) / portfolio_value
                if portfolio_value > 0
                else 0.0
            )
            tolerance = max(0.0025, share_tolerance)
            if abs(actual - target) > tolerance:
                deviations[symbol.value] = {
                    "target": target,
                    "actual": actual,
                    "tolerance": tolerance,
                }

        if outside_targets:
            state["adjustment_cycles"] += 1
            if state["adjustment_cycles"] > state["max_adjustment_cycles"]:
                self._af_fail_rebalance(
                    "target weights did not converge within the adjustment limit"
                )
                return
            state["phase"] = "await_sizing_bar"
            self._af_record_rebalance_event(
                "staged_rebalance_reprice_required",
                {
                    "tag": tag,
                    "outside_targets": outside_targets,
                    "adjustment_cycle": state["adjustment_cycles"],
                },
            )
            return
        self._af_record_rebalance_event(
            "staged_rebalance_completed",
            {
                "tag": tag,
                "targets": {symbol.value: weight for symbol, weight in targets.items()},
                "actual_weights": actual_weights,
                "post_fill_weight_drift": deviations,
            },
        )
        self.af_clear_pending_rebalance()

    def _af_fail_rebalance(self, reason: str):
        state = self._af_rebalance_state
        if state is None:
            return
        state["phase"] = "failed"
        state["failure_reason"] = reason
        state["active_order_ids"] = set()
        self._af_record_rebalance_event(
            "staged_rebalance_failed",
            {
                "tag": state["tag"],
                "reason": reason,
                "targets": {
                    symbol.value: weight for symbol, weight in state["targets"].items()
                },
            },
        )

    def _af_advance_rebalance(self):
        state = self._af_rebalance_state
        if state is None or state["active_order_ids"]:
            return
        if state["phase"] in {"opening_removals", "adjust_reductions"}:
            state["phase"] = "await_sizing_bar"
        elif state["phase"] == "adjust_buys":
            state["phase"] = "await_validation"

    def _af_start_rebalance(self, targets, tag: str):
        self._af_pending_target_weights = targets
        self._af_pending_rebalance_tag = tag
        self._af_rebalance_state = {
            "phase": "created",
            "tag": tag,
            "targets": targets,
            "active_order_ids": set(),
            "orders": {},
            "closed_order_ids": set(),
            "failure_reason": None,
            "expected_cancel_ids": set(),
            "replacement": None,
            "repricing": False,
            "adjustment_cycles": 0,
            "max_adjustment_cycles": 5,
            "sizing_date": None,
            "phase_submitted_date": None,
        }
        self._af_submit_opening_orders()

    def _af_activate_replacement(self):
        state = self._af_rebalance_state
        if state is None or state.get("replacement") is None:
            return
        replacement = state["replacement"]
        previous_tag = state["tag"]
        self._af_record_rebalance_event(
            "staged_rebalance_replaced",
            {
                "previous_tag": previous_tag,
                "replacement_tag": replacement["tag"],
            },
        )
        self._af_start_rebalance(replacement["targets"], replacement["tag"])

    def _af_continue_rebalance_on_data(self):
        state = self._af_rebalance_state
        if state is None or state["phase"] == "failed":
            return
        today = str(self.time.date())

        if state["phase"] == "adjust_buys" and state["active_order_ids"]:
            if state.get("phase_submitted_date") == today:
                return
            state["repricing"] = True
            state["expected_cancel_ids"] = set(state["active_order_ids"])
            for order_id in sorted(state["active_order_ids"]):
                ticket = state["orders"][order_id]["ticket"]
                ticket.cancel("AlphaForge daily target repricing")
            return

        if state["active_order_ids"]:
            return
        if state["phase"] == "await_validation":
            self._af_complete_rebalance()
            return
        if state["phase"] == "await_sizing_bar":
            state["sizing_date"] = today
            self._af_submit_adjustment_phase(reductions=True)

    def af_rebalance_to_weights(self, target_weights, tag: str):
        """Rebalance daily data with ordered reductions and capped buy prices.

        Non-target holdings leave first. Final quantities are calculated from a
        completed daily bar. Buy limit prices cap their total position value at
        the requested weight; unfilled orders are repriced on the next completed
        bar. Pending state remains until weights converge or explicitly fail.
        """
        clean = {
            symbol: max(0.0, float(weight))
            for symbol, weight in target_weights.items()
            if float(weight) > 0
        }
        if not clean:
            self.af_liquidate_all(tag)
            return

        state = self._af_rebalance_state
        if state is not None and state.get("phase") != "failed":
            if state["active_order_ids"]:
                state["replacement"] = {"targets": clean, "tag": tag}
                state["phase"] = "replacement_cancel"
                state["expected_cancel_ids"] = set(state["active_order_ids"])
                self._af_record_rebalance_event(
                    "staged_rebalance_replacement_requested",
                    {
                        "previous_tag": state["tag"],
                        "replacement_tag": tag,
                        "cancel_order_ids": sorted(state["active_order_ids"]),
                    },
                )
                for order_id in sorted(state["active_order_ids"]):
                    state["orders"][order_id]["ticket"].cancel(
                        "AlphaForge target replacement"
                    )
                return
            state["replacement"] = {"targets": clean, "tag": tag}
            self._af_activate_replacement()
            return

        self._af_start_rebalance(clean, tag)

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
        self._af_continue_rebalance_on_data()
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
        state = self._af_rebalance_state
        if state is not None and int(order_event.order_id) in state["orders"]:
            order_id = int(order_event.order_id)
            metadata = state["orders"][order_id]
            expected_cancel = order_id in state.get("expected_cancel_ids", set())
            if self._af_order_status_failed(order_event.status) and not expected_cancel:
                self._af_fail_rebalance(
                    f"{metadata['purpose']} order {order_id} ended as "
                    f"{self._af_order_status_text(order_event.status)}: {event['message']}"
                )
            elif self._af_order_status_closed(order_event.status):
                state["closed_order_ids"].add(order_id)
                state["active_order_ids"].discard(order_id)
                state.get("expected_cancel_ids", set()).discard(order_id)
                if expected_cancel and not state["active_order_ids"]:
                    if state.get("replacement") is not None:
                        self._af_activate_replacement()
                    else:
                        state["repricing"] = False
                        state["phase"] = "await_sizing_bar"
                else:
                    self._af_advance_rebalance()
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
            "rebalances": self._af_rebalance_events,
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
