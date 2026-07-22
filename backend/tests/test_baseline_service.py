from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.repositories import SQLiteRepository
from app.schemas import BattleCreate, ExperimentContract
from app.services.baseline_service import BASELINES, BaselineService


SYMBOLS = ("MSFT", "AAPL", "NVDA", "GOOGL", "AMZN")


class FakeWorker:
    def __init__(self):
        self.submissions = []

    def submit(self, strategy_id, parameters):
        self.submissions.append((strategy_id, dict(parameters)))
        return {"run_id": f"run-{len(self.submissions)}", "state": "queued"}

    def job(self, run_id):
        return {"run_id": run_id, "state": "completed", "result_path": "result.json"}

    def result(self, run_id):
        return {
            "status": "completed",
            "summary": {
                "cagr": 0.10,
                "sharpe_ratio": 1.0,
                "maximum_drawdown": 0.12,
            },
            "performance": {"equity_curve": [], "drawdown_curve": []},
            "evaluation": {"eligible_for_comparison": True},
        }


class BaselineServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        repository = SQLiteRepository(Path(self.tempdir.name) / "test.db")
        self.worker = FakeWorker()
        self.service = BaselineService(repository, self.worker, set(SYMBOLS))

    def tearDown(self):
        self.tempdir.cleanup()

    def contract(self):
        return ExperimentContract(
            symbols=SYMBOLS,
            start_date=date(2016, 1, 4),
            end_date=date(2026, 6, 30),
            initial_cash=100_000,
            data_version="test-data-v1",
        )

    def test_contract_hash_is_order_stable(self):
        first = self.contract()
        second = ExperimentContract.model_validate(first.model_dump())
        self.assertEqual(first.sha256(), second.sha256())
        self.assertEqual(len(first.sha256()), 64)

    def test_four_baselines_receive_identical_contract(self):
        battle = self.service.create_battle(
            BattleCreate(name="test", experiment_contract=self.contract())
        )
        batch = self.service.run_baselines(battle.battle_id)
        self.assertEqual(batch.state, "queued")
        self.assertEqual(len(self.worker.submissions), 4)
        self.assertEqual(
            [item[0] for item in self.worker.submissions],
            [item["strategy_id"] for item in BASELINES],
        )
        parameter_sets = [parameters for _, parameters in self.worker.submissions]
        self.assertTrue(all(parameters == parameter_sets[0] for parameters in parameter_sets))
        self.assertEqual(
            parameter_sets[0]["experiment_contract_hash"], battle.contract_hash
        )

        completed = self.service.refresh_batch(batch.batch_id)
        self.assertEqual(completed.state, "completed")
        self.assertTrue(all(run.eligible_for_comparison for run in completed.runs))
        self.assertTrue(all(run.result_hash for run in completed.runs))

    def test_rejects_symbols_outside_whitelist(self):
        contract = self.contract().model_copy(update={"symbols": (*SYMBOLS[:-1], "TSLA")})
        with self.assertRaises(ValueError):
            self.service.create_battle(
                BattleCreate(name="invalid", experiment_contract=contract)
            )


if __name__ == "__main__":
    unittest.main()
