from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.repositories import SQLiteRepository
from app.schemas import BaselineBatchView, BaselineRunView, BattleCreate, BattleView
from app.services.worker_client import LeanWorkerClient, WorkerClientError


BASELINES = (
    {
        "strategy_id": "classic_30_stock_top3_momentum_v1",
        "display_name": "Momentum Rank",
        "family": "Traditional",
        "lesson": "Persistent medium-term trends can be ranked with a transparent signal.",
    },
    {
        "strategy_id": "classic_30_stock_mean_reversion_v1",
        "display_name": "Mean Reversion",
        "family": "Traditional",
        "lesson": "Recent losers may rebound, but a market risk gate helps avoid severe downtrends.",
    },
    {
        "strategy_id": "ml_30_stock_gradient_boosting_v1",
        "display_name": "Gradient Boosting",
        "family": "Machine Learning",
        "lesson": "Walk-forward non-linear ranking combines several weak predictive features.",
    },
    {
        "strategy_id": "hybrid_30_stock_ml_momentum_min_variance_v1",
        "display_name": "Hybrid ML + Minimum Variance",
        "family": "Hybrid",
        "lesson": "Signal ranking and covariance-aware sizing solve different portfolio problems.",
    },
)

TERMINAL_STATES = {"completed", "completed_with_data_gaps", "failed", "timeout"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def result_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class BaselineService:
    def __init__(
        self,
        repository: SQLiteRepository,
        worker: LeanWorkerClient,
        allowed_symbols: set[str],
    ):
        self.repository = repository
        self.worker = worker
        self.allowed_symbols = {symbol.upper() for symbol in allowed_symbols}

    def create_battle(self, request: BattleCreate) -> BattleView:
        contract = request.experiment_contract
        unknown = sorted(set(contract.symbols).difference(self.allowed_symbols))
        if unknown:
            raise ValueError(f"Symbols outside whitelist: {unknown}")
        created_at = utc_now()
        record = {
            "battle_id": f"btl-{uuid.uuid4().hex[:12]}",
            "name": request.name,
            "status": "contract_locked",
            "contract_hash": contract.sha256(),
            "experiment_contract": contract.canonical_payload(),
            "created_at": created_at,
        }
        self.repository.create_battle(record)
        return BattleView.model_validate(record)

    def get_battle(self, battle_id: str) -> BattleView | None:
        record = self.repository.get_battle(battle_id)
        return BattleView.model_validate(record) if record else None

    def _parameters(self, battle: dict[str, Any]) -> dict[str, str]:
        contract = battle["experiment_contract"]
        return {
            "start_date": contract["start_date"],
            "end_date": contract["end_date"],
            "initial_cash": str(contract["initial_cash"]),
            "symbols": ",".join(contract["symbols"]),
            "top_k": str(contract["top_k"]),
            "target_gross": str(contract["target_gross"]),
            "max_position_weight": str(contract["max_position_weight"]),
            "max_drawdown": str(contract["max_drawdown"]),
            "transaction_cost_bps": str(contract["transaction_cost_bps"]),
            "slippage_bps": str(contract["slippage_bps"]),
            "risk_filter_enabled": "true",
            "risk_sma_period": str(contract["risk_sma_period"]),
            "random_seed": str(contract["random_seed"]),
            "experiment_contract_hash": battle["contract_hash"],
            "data_version": contract["data_version"],
        }

    def run_baselines(self, battle_id: str) -> BaselineBatchView:
        battle = self.repository.get_battle(battle_id)
        if battle is None:
            raise KeyError("Unknown battle_id")
        latest = self.repository.latest_batch(battle_id)
        if latest and latest["state"] in {"submitting", "queued", "running"}:
            return self._view(latest, battle["contract_hash"])

        timestamp = utc_now()
        batch = {
            "batch_id": f"base-{uuid.uuid4().hex[:12]}",
            "battle_id": battle_id,
            "state": "submitting",
            "created_at": timestamp,
            "updated_at": timestamp,
            "error": None,
        }
        runs = [
            {
                "strategy_id": item["strategy_id"],
                "display_name": item["display_name"],
                "family": item["family"],
                "state": "submitting",
            }
            for item in BASELINES
        ]
        self.repository.create_batch(batch, runs)

        errors = []
        parameters = self._parameters(battle)
        for item in BASELINES:
            try:
                submitted = self.worker.submit(item["strategy_id"], parameters)
                self.repository.update_run(
                    batch["batch_id"],
                    item["strategy_id"],
                    state=submitted.get("state", "queued"),
                    worker_run_id=submitted["run_id"],
                )
            except WorkerClientError as exc:
                errors.append(f"{item['display_name']}: {exc}")
                self.repository.update_run(
                    batch["batch_id"],
                    item["strategy_id"],
                    state="failed",
                    error=str(exc),
                )

        state = "failed" if len(errors) == len(BASELINES) else "queued"
        self.repository.update_batch(
            batch["batch_id"],
            state=state,
            updated_at=utc_now(),
            error="; ".join(errors) if errors else None,
        )
        stored = self.repository.get_batch(batch["batch_id"])
        return self._view(stored, battle["contract_hash"])

    def refresh_batch(self, batch_id: str) -> BaselineBatchView:
        batch = self.repository.get_batch(batch_id)
        if batch is None:
            raise KeyError("Unknown baseline batch")
        battle = self.repository.get_battle(batch["battle_id"])
        if battle is None:
            raise KeyError("Unknown battle_id")

        refresh_errors = []
        for run in batch["runs"]:
            if not run["worker_run_id"] or run["state"] in TERMINAL_STATES:
                continue
            try:
                worker_record = self.worker.job(run["worker_run_id"])
                state = worker_record.get("state", "failed")
                result = None
                digest = None
                if state in TERMINAL_STATES and worker_record.get("result_path"):
                    result = self.worker.result(run["worker_run_id"])
                    digest = result_digest(result)
                self.repository.update_run(
                    batch_id,
                    run["strategy_id"],
                    state=state,
                    result=result,
                    result_hash=digest,
                    error=worker_record.get("error"),
                )
            except WorkerClientError as exc:
                refresh_errors.append(f"{run['display_name']}: {exc}")

        batch = self.repository.get_batch(batch_id)
        states = {run["state"] for run in batch["runs"]}
        if states == {"completed"}:
            aggregate_state = "completed"
        elif states.issubset(TERMINAL_STATES):
            aggregate_state = (
                "completed_with_data_gaps"
                if states.issubset({"completed", "completed_with_data_gaps"})
                else "failed"
            )
        elif "running" in states:
            aggregate_state = "running"
        else:
            aggregate_state = "queued"
        self.repository.update_batch(
            batch_id,
            state=aggregate_state,
            updated_at=utc_now(),
            error="; ".join(refresh_errors) if refresh_errors else batch.get("error"),
        )
        return self._view(
            self.repository.get_batch(batch_id), battle["contract_hash"]
        )

    def latest_batch(self, battle_id: str, refresh: bool = True) -> BaselineBatchView | None:
        battle = self.repository.get_battle(battle_id)
        if battle is None:
            raise KeyError("Unknown battle_id")
        batch = self.repository.latest_batch(battle_id)
        if batch is None:
            return None
        if refresh and batch["state"] not in TERMINAL_STATES:
            return self.refresh_batch(batch["batch_id"])
        return self._view(batch, battle["contract_hash"])

    def _view(self, batch: dict[str, Any], contract_hash: str) -> BaselineBatchView:
        runs = []
        for run in batch["runs"]:
            result = run.get("result") or {}
            evaluation = result.get("evaluation", {})
            runs.append(
                BaselineRunView(
                    strategy_id=run["strategy_id"],
                    display_name=run["display_name"],
                    family=run["family"],
                    worker_run_id=run.get("worker_run_id"),
                    state=run["state"],
                    eligible_for_comparison=bool(
                        evaluation.get("eligible_for_comparison", False)
                    ),
                    result_hash=run.get("result_hash"),
                    summary=result.get("summary", {}),
                    performance=result.get("performance", {}),
                    error=run.get("error"),
                )
            )
        return BaselineBatchView(
            batch_id=batch["batch_id"],
            battle_id=batch["battle_id"],
            state=batch["state"],
            contract_hash=contract_hash,
            created_at=batch["created_at"],
            updated_at=batch["updated_at"],
            runs=runs,
            error=batch.get("error"),
        )
