from datetime import date
import importlib.util
from pathlib import Path
import tempfile
import unittest


def load_module():
    path = Path(__file__).resolve().parents[1] / "tools" / "sync_tiingo_data.py"
    spec = importlib.util.spec_from_file_location("sync_tiingo_data_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DataSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_adjusted_fields_are_preferred(self):
        row = self.module.normalize_row(
            {
                "date": "2026-07-17T00:00:00.000Z",
                "open": 100,
                "high": 102,
                "low": 99,
                "close": 101,
                "volume": 1000,
                "adjOpen": 50,
                "adjHigh": 51,
                "adjLow": 49.5,
                "adjClose": 50.5,
                "adjVolume": 2000,
                "divCash": 0.25,
                "splitFactor": 2,
            }
        )
        self.assertEqual(row["date"], date(2026, 7, 17))
        self.assertEqual(row["open"], 50)
        self.assertEqual(row["close"], 50.5)
        self.assertEqual(row["volume"], 2000)

    def test_daily_zip_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aapl.zip"
            rows = {
                date(2026, 7, 16): "20260716 00:00,10000,11000,9000,10500,100",
                date(2026, 7, 17): "20260717 00:00,10500,11500,10000,11000,120",
            }
            self.module.write_daily_zip(path, "aapl", rows)
            self.assertEqual(self.module.read_existing_zip(path, "aapl"), rows)


    def test_catalog_ready_for_complete_universe(self):
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = Path(__file__).resolve().parents[1]
            universe, entries = self.module.load_universe(
                project / "config" / "universe_whitelist_v1.0.json"
            )
            days = []
            current = date(2020, 1, 1)
            while len(days) < 1005:
                if current.weekday() < 5:
                    days.append(current)
                current += timedelta(days=1)
            for entry in entries:
                ticker = entry["lean_ticker"].lower()
                rows = {
                    day: f"{day.strftime('%Y%m%d')} 00:00,10000,11000,9000,10500,100"
                    for day in days
                }
                self.module.write_daily_zip(
                    root / "equity/usa/daily" / f"{ticker}.zip",
                    ticker,
                    rows,
                )
                self.module.write_compatibility_files(root, entry, days[0])
            manifest = self.module.write_catalog(
                data_root=root,
                universe=universe,
                entries=entries,
                provider_start=days[0],
                requested_end=days[-1],
                errors=[],
                corporate_actions={},
                sync_mode="full",
            )
            self.assertTrue(manifest["ready"])
            self.assertTrue((root / "alphaforge-catalog/availability.csv").is_file())
            self.assertTrue((root / "alphaforge-catalog/checksums.json").is_file())

    def test_universe_has_30_plus_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        universe, entries = self.module.load_universe(
            root / "config" / "universe_whitelist_v1.0.json"
        )
        self.assertEqual(len(universe["tradable_symbols"]), 30)
        self.assertEqual(len(entries), 32)
        tickers = {entry["lean_ticker"] for entry in entries}
        self.assertIn("SPY", tickers)
        self.assertIn("QQQ", tickers)
        self.assertIn("BRK.B", tickers)


if __name__ == "__main__":
    unittest.main()
