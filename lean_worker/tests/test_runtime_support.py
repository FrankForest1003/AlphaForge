from datetime import date, datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest

import pandas as pd


def load_runtime_support():
    fake = types.ModuleType("AlgorithmImports")
    fake.QCAlgorithm = type("QCAlgorithm", (), {})
    fake.FeeModel = type("FeeModel", (), {})
    fake.OrderFee = type("OrderFee", (), {})
    fake.CashAmount = type("CashAmount", (), {})
    fake.DataNormalizationMode = types.SimpleNamespace(RAW="RAW")
    sys.modules["AlgorithmImports"] = fake
    path = Path(__file__).resolve().parents[1] / "runtime_support" / "alphaforge_base.py"
    spec = importlib.util.spec_from_file_location("alphaforge_base_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DotNetDateTimeLike:
    def ToString(self, fmt=None):
        return "2026-07-20T12:34:56.0000000Z" if fmt == "o" else "fallback"


class SymbolLike:
    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        return isinstance(other, SymbolLike) and self.value == other.value


class HoldingLike:
    def __init__(self, quantity=0, price=0):
        self.quantity = quantity
        self.average_price = price
        self.holdings_cost = quantity * price
        self.unrealized_profit = 0
        self.unrealized_profit_percent = 0
        self.holdings_value = quantity * price

    @property
    def invested(self):
        return self.quantity != 0


class PortfolioLike:
    def __init__(self, holdings, total_portfolio_value=100_000):
        self.holdings = holdings
        self.total_portfolio_value = total_portfolio_value
        self.cash = total_portfolio_value - sum(
            item.holdings_value for item in holdings.values()
        )
        self.total_holdings_value = total_portfolio_value - self.cash

    def __getitem__(self, symbol):
        return self.holdings[symbol]


class TransactionsLike:
    def __init__(self):
        self.orders = {}

    def get_order_by_id(self, order_id):
        return self.orders.get(order_id)

    def get_open_orders(self):
        return []


class TicketLike:
    def __init__(self, order_id):
        self.order_id = order_id
        self.cancel_requests = []

    def cancel(self, message):
        self.cancel_requests.append(message)


class OrderEventLike:
    def __init__(self, order_id, symbol, status, fill_price=0, fill_quantity=0, message=""):
        self.order_id = order_id
        self.symbol = symbol
        self.status = status
        self.fill_price = fill_price
        self.fill_quantity = fill_quantity
        self.message = message
        self.order_fee = types.SimpleNamespace(
            value=types.SimpleNamespace(amount=0)
        )


class RuntimeSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime_support()

    def test_python_datetime_uses_isoformat(self):
        value = datetime(2026, 7, 20, 12, 34, 56, 123456)
        self.assertEqual(
            self.module._time_text(value),
            "2026-07-20T12:34:56.123456",
        )

    def test_python_date_uses_isoformat(self):
        self.assertEqual(
            self.module._time_text(date(2026, 7, 20)),
            "2026-07-20",
        )

    def test_dotnet_datetime_uses_roundtrip_format(self):
        self.assertEqual(
            self.module._time_text(DotNetDateTimeLike()),
            "2026-07-20T12:34:56.0000000Z",
        )

    def test_none_is_empty(self):
        self.assertEqual(self.module._time_text(None), "")

    def test_history_splitter_skips_absent_symbol_without_key_error(self):
        index = pd.MultiIndex.from_tuples(
            [
                ("AAPL", pd.Timestamp("2016-01-04")),
                ("AAPL", pd.Timestamp("2016-01-05")),
                ("SPY", pd.Timestamp("2016-01-04")),
            ],
            names=["symbol", "time"],
        )
        history = pd.DataFrame({"Close": [100.0, 101.0, 200.0]}, index=index)
        frames = self.module.af_split_history_frames(history)
        self.assertEqual(sorted(frames), ["AAPL", "SPY"])
        self.assertNotIn("LIN", frames)
        self.assertEqual(list(frames["AAPL"].columns), ["close"])
        self.assertEqual(len(frames["AAPL"]), 2)

    def test_history_splitter_accepts_symbol_value_property(self):
        index = pd.MultiIndex.from_tuples(
            [(SymbolLike("MSFT"), pd.Timestamp("2020-01-02"))],
            names=["symbol", "time"],
        )
        history = pd.DataFrame({"close": [150.0]}, index=index)
        frames = self.module.af_split_history_frames(history)
        self.assertIn("MSFT", frames)

    def test_security_benchmark_reuses_existing_subscription(self):
        algorithm = self.module.AlphaForgeBaseAlgorithm()
        symbol = object()
        security = types.SimpleNamespace(price=123.45)
        algorithm.securities = {symbol: security}
        captured = {}
        algorithm.set_benchmark = lambda callback: captured.setdefault("callback", callback)
        algorithm.af_use_security_benchmark(symbol)
        self.assertIs(algorithm._af_benchmark_symbol, symbol)
        self.assertEqual(captured["callback"](None), 123.45)

    def _execution_algorithm(self):
        algorithm = self.module.AlphaForgeBaseAlgorithm()
        old = SymbolLike("OLD")
        meta = SymbolLike("META")
        nvda = SymbolLike("NVDA")
        amzn = SymbolLike("AMZN")
        symbols = (old, meta, nvda, amzn)
        holdings = {
            old: HoldingLike(1000, 95),
            meta: HoldingLike(),
            nvda: HoldingLike(),
            amzn: HoldingLike(),
        }
        prices = {old: 95, meta: 391.39, nvda: 615, amzn: 159}
        algorithm._af_tracked_symbols = list(symbols)
        algorithm._af_pending_target_weights = None
        algorithm._af_pending_rebalance_tag = ""
        algorithm._af_rebalance_state = None
        algorithm._af_rebalance_events = []
        algorithm._af_signals = []
        algorithm._af_order_events = []
        algorithm._af_orders = {}
        algorithm._af_position_snapshots = []
        algorithm._af_equity_curve = []
        algorithm._af_benchmark_curve = []
        algorithm._af_benchmark_symbol = None
        algorithm._af_last_daily_snapshot = None
        algorithm.is_warming_up = False
        algorithm.time = datetime(2024, 2, 1, 9, 25)
        algorithm.portfolio = PortfolioLike(holdings)
        algorithm.securities = {
            symbol: types.SimpleNamespace(price=price)
            for symbol, price in prices.items()
        }
        algorithm.transactions = TransactionsLike()
        submitted = []
        next_id = iter(range(1, 100))

        def submit(kind, symbol, quantity, **kwargs):
            order_id = next(next_id)
            ticket = TicketLike(order_id)
            algorithm.transactions.orders[order_id] = types.SimpleNamespace(
                id=order_id,
                time=algorithm.time,
                symbol=symbol,
                quantity=quantity,
                type=kind,
                status="Submitted",
                tag=kwargs.get("tag", ""),
                price=0,
            )
            submitted.append((kind, order_id, symbol, quantity, kwargs))
            return ticket

        algorithm.market_on_open_order = lambda symbol, quantity, **kwargs: submit(
            "MOO", symbol, quantity, **kwargs
        )
        algorithm.limit_order = lambda symbol, quantity, limit_price, **kwargs: submit(
            "Limit", symbol, quantity, limit_price=limit_price, **kwargs
        )
        return algorithm, symbols, submitted

    @staticmethod
    def _apply_fill(algorithm, order_id, symbol, fill_price, quantity_delta):
        holding = algorithm.portfolio[symbol]
        holding.quantity += quantity_delta
        holding.holdings_value = holding.quantity * fill_price
        algorithm.securities[symbol].price = fill_price
        algorithm.on_order_event(
            OrderEventLike(
                order_id,
                symbol,
                "Filled",
                fill_price=fill_price,
                fill_quantity=0,
            )
        )

    def test_gap_safe_rebalance_keeps_pending_until_final_orders_close(self):
        algorithm, symbols, submitted = self._execution_algorithm()
        old, meta, nvda, amzn = symbols
        targets = {meta: 0.316666, nvda: 0.316666, amzn: 0.316666}

        algorithm.af_rebalance_to_weights(targets, "monthly")

        self.assertEqual(algorithm._af_rebalance_state["phase"], "opening_removals")
        self.assertEqual(
            [(kind, symbol.value, quantity) for kind, _, symbol, quantity, _ in submitted],
            [("MOO", "OLD", -1000.0)],
        )
        self.assertIsNotNone(algorithm._af_pending_target_weights)

        _, removal_id, _, _, _ = submitted[0]
        self._apply_fill(algorithm, removal_id, old, 95, -1000)
        self.assertEqual(algorithm._af_rebalance_state["phase"], "await_sizing_bar")

        completed_prices = {meta: 455.65, nvda: 630, amzn: 170}
        for symbol, price in completed_prices.items():
            algorithm.securities[symbol].price = price
        algorithm.time = datetime(2024, 2, 2, 16, 0)
        algorithm.on_data(None)

        self.assertEqual(algorithm._af_rebalance_state["phase"], "adjust_buys")
        buy_orders = [item for item in submitted if item[0] == "Limit"]
        meta_buy = next(item for item in buy_orders if item[2] == meta)
        self.assertEqual(meta_buy[3], 69)
        self.assertAlmostEqual(
            meta_buy[4]["limit_price"],
            100_000 * targets[meta] / 69,
        )
        self.assertIsNotNone(algorithm._af_pending_target_weights)

        for _, order_id, symbol, quantity, _ in buy_orders:
            self._apply_fill(
                algorithm,
                order_id,
                symbol,
                completed_prices[symbol],
                quantity,
            )

        self.assertEqual(algorithm._af_rebalance_state["phase"], "await_validation")
        algorithm.time = datetime(2024, 2, 5, 16, 0)
        algorithm.on_data(None)
        self.assertIsNone(algorithm._af_rebalance_state)
        self.assertIsNone(algorithm._af_pending_target_weights)
        self.assertEqual(
            algorithm._af_rebalance_events[-1]["name"],
            "staged_rebalance_completed",
        )

    def test_unfilled_limit_is_canceled_and_repriced_from_next_completed_bar(self):
        algorithm, symbols, submitted = self._execution_algorithm()
        old, meta, nvda, amzn = symbols
        targets = {meta: 0.316666, nvda: 0.316666, amzn: 0.316666}
        algorithm.af_rebalance_to_weights(targets, "monthly")
        self._apply_fill(algorithm, submitted[0][1], old, 95, -1000)

        for symbol, price in {meta: 455.65, nvda: 630, amzn: 170}.items():
            algorithm.securities[symbol].price = price
        algorithm.time = datetime(2024, 2, 2, 16, 0)
        algorithm.on_data(None)
        first_buys = [item for item in submitted if item[0] == "Limit"]
        meta_buy = next(item for item in first_buys if item[2] == meta)
        for item in first_buys:
            if item[2] != meta:
                self._apply_fill(algorithm, item[1], item[2], algorithm.securities[item[2]].price, item[3])

        algorithm.time = datetime(2024, 2, 5, 16, 0)
        algorithm.on_data(None)
        meta_ticket = algorithm._af_rebalance_state["orders"][meta_buy[1]]["ticket"]
        self.assertEqual(meta_ticket.cancel_requests, ["AlphaForge daily target repricing"])
        algorithm.on_order_event(
            OrderEventLike(meta_buy[1], meta, "Canceled", message="repricing")
        )
        self.assertEqual(algorithm._af_rebalance_state["phase"], "await_sizing_bar")

        algorithm.securities[meta].price = 466.0
        algorithm.time = datetime(2024, 2, 6, 16, 0)
        algorithm.on_data(None)
        repriced_meta = [
            item for item in submitted if item[0] == "Limit" and item[2] == meta
        ][-1]
        self.assertNotEqual(repriced_meta[1], meta_buy[1])
        self.assertEqual(repriced_meta[3], 67)
        self.assertLessEqual(
            repriced_meta[3] * repriced_meta[4]["limit_price"],
            100_000 * targets[meta] + 1e-9,
        )
        self.assertIsNotNone(algorithm._af_pending_target_weights)

    def test_new_target_replaces_incomplete_rebalance_instead_of_being_skipped(self):
        algorithm, symbols, submitted = self._execution_algorithm()
        old, meta, nvda, amzn = symbols
        algorithm.af_rebalance_to_weights({old: 0.95}, "old target")
        self.assertEqual(algorithm._af_rebalance_state["phase"], "await_sizing_bar")

        replacement = {meta: 0.316666, nvda: 0.316666, amzn: 0.316666}
        algorithm.af_rebalance_to_weights(replacement, "new target")

        self.assertEqual(algorithm._af_rebalance_state["tag"], "new target")
        self.assertEqual(algorithm._af_rebalance_state["targets"], replacement)
        self.assertEqual(algorithm._af_rebalance_state["phase"], "opening_removals")
        self.assertEqual(
            [(kind, symbol.value, quantity) for kind, _, symbol, quantity, _ in submitted],
            [("MOO", "OLD", -1000.0)],
        )
        self.assertIn(
            "staged_rebalance_replaced",
            [event["name"] for event in algorithm._af_rebalance_events],
        )

    def test_target_delta_ignores_position_within_one_share_tolerance(self):
        algorithm, symbols, _ = self._execution_algorithm()
        old, meta, _, _ = symbols
        algorithm.portfolio[old].quantity = 0
        algorithm.portfolio[old].holdings_value = 0
        algorithm.portfolio[meta].quantity = 69
        algorithm.portfolio[meta].holdings_value = 31_439.85
        algorithm.securities[meta].price = 455.65
        algorithm.af_rebalance_to_weights({meta: 0.316666}, "within tolerance")

        self.assertEqual(algorithm._af_target_deltas(), {})

    def test_post_fill_market_drift_does_not_trigger_daily_churn(self):
        algorithm, symbols, _ = self._execution_algorithm()
        old, meta, nvda, amzn = symbols
        algorithm.portfolio[old].quantity = 0
        algorithm.portfolio[old].holdings_value = 0
        for symbol, quantity, price in (
            (meta, 68, 464.09),
            (nvda, 455, 72.0072),
            (amzn, 182, 174.45),
        ):
            algorithm.portfolio[symbol].quantity = quantity
            algorithm.portfolio[symbol].holdings_value = quantity * price
            algorithm.securities[symbol].price = price
        algorithm.portfolio.total_portfolio_value = 101_550.81
        targets = {meta: 0.316666, nvda: 0.316666, amzn: 0.316666}
        algorithm._af_start_rebalance(targets, "filled target")
        algorithm._af_rebalance_state["phase"] = "await_validation"

        algorithm._af_complete_rebalance()

        self.assertIsNone(algorithm._af_rebalance_state)
        completed = algorithm._af_rebalance_events[-1]
        self.assertEqual(completed["name"], "staged_rebalance_completed")
        self.assertIn("META", completed["payload"]["post_fill_weight_drift"])

    def test_invalid_buy_is_explicit_failure_and_does_not_clear_pending(self):
        algorithm, symbols, submitted = self._execution_algorithm()
        old, meta, nvda, amzn = symbols
        algorithm.af_rebalance_to_weights(
            {meta: 0.316666, nvda: 0.316666, amzn: 0.316666},
            "monthly",
        )
        self._apply_fill(algorithm, submitted[0][1], old, 95, -1000)
        for symbol, price in {meta: 455.65, nvda: 630, amzn: 170}.items():
            algorithm.securities[symbol].price = price
        algorithm.time = datetime(2024, 2, 2, 16, 0)
        algorithm.on_data(None)

        buy_order = next(item for item in submitted if item[0] == "Limit")
        _, order_id, symbol, _, _ = buy_order
        algorithm.on_order_event(
            OrderEventLike(
                order_id,
                symbol,
                "Invalid",
                message="Insufficient buying power",
            )
        )

        self.assertEqual(algorithm._af_rebalance_state["phase"], "failed")
        self.assertIsNotNone(algorithm._af_pending_target_weights)
        self.assertIn(
            "Insufficient buying power",
            algorithm._af_rebalance_state["failure_reason"],
        )
        self.assertEqual(
            algorithm._af_rebalance_events[-1]["name"],
            "staged_rebalance_failed",
        )


if __name__ == "__main__":
    unittest.main()
