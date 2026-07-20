from pathlib import Path
import json
import tempfile
import unittest

from worker.result_parser import parse_log_file, reconstruct_closed_trades


class ParserTests(unittest.TestCase):
    def test_closed_trade(self):
        trades = reconstruct_closed_trades([
            {"symbol": "AAPL", "fill_quantity": 10, "fill_price": 100, "time": "t1", "order_id": 1},
            {"symbol": "AAPL", "fill_quantity": -10, "fill_price": 110, "time": "t2", "order_id": 2},
        ])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["profit_loss"], 100)

    def test_parser_merges_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "console.log"
            detail = root / "alphaforge_details.json"
            log.write_text(
                "STATISTICS:: Total Orders 2\n"
                "STATISTICS:: Sharpe Ratio 1.2\n"
                "DATA USAGE:: Failed data requests 0\n"
                "Engine.Main(): Analysis Complete.\n"
                "PythonInitializer.Shutdown(): ended\n"
                "Program.Main(): Exiting Lean...\n"
                "MARKER\n",
                encoding="utf-8",
            )
            detail.write_text(json.dumps({
                "equity_curve": [{"time": "t", "portfolio_value": 100, "cash": 100, "holdings_value": 0}],
                "position_snapshots": [{"positions": []}],
                "orders": [], "order_events": [], "signals": [],
                "ml": {"training_runs": [], "predictions": [], "model_artifacts": []},
            }), encoding="utf-8")
            result = parse_log_file(
                log, detail_path=detail, exit_code=0, run_id="r",
                algorithm_class="A", algorithm_file="a.py",
                expected_marker="MARKER", timed_out=False,
                manifest={"strategy": {}, "environment": {}},
            )
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["engine"]["clean_shutdown"])
            self.assertEqual(result["summary"]["total_orders"], 2)


if __name__ == "__main__":
    unittest.main()
