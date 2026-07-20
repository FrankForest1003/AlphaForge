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
        class SymbolLike:
            def __init__(self, value):
                self.value = value

            def __hash__(self):
                return hash(self.value)

            def __eq__(self, other):
                return isinstance(other, SymbolLike) and self.value == other.value

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


if __name__ == "__main__":
    unittest.main()
