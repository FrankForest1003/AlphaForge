from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.repositories import SQLiteRepository
from app.schemas import BattleCreate, ExperimentContract, GuidedStrategySpec
from app.services.baseline_service import (
    BASELINES,
    GUIDED_STRATEGIES,
    BaselineService,
    GUIDED_BY_ID,
)


SYMBOLS = ("MSFT", "AAPL", "NVDA", "GOOGL", "AMZN")


class FakeWorker:
    def __init__(self):
        self.submissions = []
        self.custom_submissions = []

    def submit(self, strategy_id, parameters):
        self.submissions.append((strategy_id, dict(parameters)))
        return {"run_id": f"run-{len(self.submissions)}", "state": "queued"}

    def submit_custom(self, algorithm_code, parameters, timeout_seconds=None):
        self.custom_submissions.append((algorithm_code, dict(parameters), timeout_seconds))
        return {"run_id": f"custom-{len(self.custom_submissions)}", "state": "queued"}

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

    def test_human_and_four_baselines_receive_the_same_contract(self):
        battle = self.service.create_battle(
            BattleCreate(name="test", experiment_contract=self.contract())
        )
        batch = self.service.run_baselines(battle.battle_id)
        self.assertEqual(batch.state, "queued")
        self.assertEqual(len(self.worker.submissions), 5)
        self.assertEqual(
            [item[0] for item in self.worker.submissions],
            [
                GUIDED_BY_ID["multi_horizon_momentum"]["worker_strategy_id"],
                *[item["strategy_id"] for item in BASELINES],
            ],
        )
        parameter_sets = [parameters for _, parameters in self.worker.submissions]
        self.assertTrue(
            all(
                parameters["experiment_contract_hash"] == battle.contract_hash
                for parameters in parameter_sets
            )
        )
        self.assertEqual(parameter_sets[0]["lookback"], "126")
        self.assertEqual(batch.runs[0].role, "human")
        self.assertTrue(all(run.role == "baseline" for run in batch.runs[1:]))

        completed = self.service.refresh_batch(batch.batch_id)
        self.assertEqual(completed.state, "completed")
        self.assertEqual(len(completed.runs), 5)
        self.assertTrue(all(run.eligible_for_comparison for run in completed.runs))
        self.assertTrue(all(run.result_hash for run in completed.runs))

    def test_guided_template_controls_human_worker_strategy(self):
        battle = self.service.create_battle(
            BattleCreate(
                name="risk adjusted human",
                experiment_contract=self.contract(),
                guided_strategy=GuidedStrategySpec(
                    template_id="risk_adjusted_momentum",
                    lookback_days=84,
                ),
            )
        )
        self.service.run_baselines(battle.battle_id)
        human_strategy_id, human_parameters = self.worker.submissions[0]
        self.assertEqual(
            human_strategy_id,
            GUIDED_BY_ID["risk_adjusted_momentum"]["worker_strategy_id"],
        )
        self.assertEqual(human_parameters["lookback"], "84")

    def test_exposed_guided_templates_do_not_reuse_public_baselines(self):
        baseline_ids = {item["strategy_id"] for item in BASELINES}
        guided_ids = {item["worker_strategy_id"] for item in GUIDED_STRATEGIES}
        self.assertTrue(guided_ids.isdisjoint(baseline_ids))

    def test_custom_code_requires_smoke_before_full_comparison(self):
        code = '''from datetime import datetime
from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm
class UserStrategy(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value or default
    def initialize_strategy(self):
        values = [self._parameter("start_date", "x"), self._parameter("end_date", "x"), self._parameter("initial_cash", "x"), self._parameter("symbols", "x"), self._parameter("top_k", "x"), self._parameter("target_gross", "x"), self._parameter("max_position_weight", "x"), self._parameter("transaction_cost_bps", "x"), self._parameter("slippage_bps", "x")]
        security = self.add_equity("SPY", Resolution.DAILY)
        self.af_configure_security(security)
        self.af_use_security_benchmark(security.symbol)
    def on_alpha_data(self, data):
        pass
    def on_alpha_end(self):
        self.debug("ALPHAFORGE_USER_STRATEGY_COMPLETED")
'''
        battle = self.service.create_battle(
            BattleCreate(
                name="custom",
                experiment_contract=self.contract(),
                strategy_mode="code",
                custom_code=code,
            )
        )
        with self.assertRaises(ValueError):
            self.service.run_baselines(battle.battle_id)
        admitted = self.service.validate_custom_code(battle.battle_id, code)
        self.assertEqual(admitted["smoke_status"], "queued")
        self.assertEqual(len(self.worker.custom_submissions), 1)
        admitted = self.service.refresh_custom_code_validation(battle.battle_id)
        self.assertTrue(admitted["accepted"])
        batch = self.service.run_baselines(battle.battle_id)
        self.assertEqual(batch.runs[0].role, "human")
        self.assertEqual(len(self.worker.custom_submissions), 2)
        self.assertEqual(len(self.worker.submissions), 4)

    def test_rejects_symbols_outside_whitelist(self):
        contract = self.contract().model_copy(update={"symbols": (*SYMBOLS[:-1], "TSLA")})
        with self.assertRaises(ValueError):
            self.service.create_battle(
                BattleCreate(name="invalid", experiment_contract=contract)
            )


if __name__ == "__main__":
    unittest.main()
