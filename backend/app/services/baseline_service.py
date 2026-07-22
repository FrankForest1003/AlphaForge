from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.repositories import SQLiteRepository
from app.schemas import BaselineBatchView, BaselineRunView, BattleCreate, BattleView
from app.services.code_validation import code_digest, validate_user_code
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

GUIDED_STRATEGIES = (
    {
        "template_id": "multi_horizon_momentum",
        "display_name": "Multi-Horizon Momentum",
        "worker_strategy_id": "guided_30_stock_multi_horizon_momentum_v1",
        "default_lookback_days": 126,
        "description": "Blend short, medium and long momentum, then require both stock and market trend confirmation.",
        "best_for": "Designed to reduce single-lookback fragility; improvement is not guaranteed.",
    },
    {
        "template_id": "risk_adjusted_momentum",
        "display_name": "Risk-Adjusted Momentum",
        "worker_strategy_id": "guided_30_stock_risk_adjusted_momentum_v1",
        "default_lookback_days": 126,
        "description": "Rank blended momentum per unit of realized volatility with stock and market trend gates.",
        "best_for": "Designed to avoid rewarding volatile momentum blindly; improvement is not guaranteed.",
    },
    {
        "template_id": "low_volatility",
        "display_name": "Low Volatility",
        "worker_strategy_id": "guided_30_stock_low_volatility_v1",
        "default_lookback_days": 63,
        "description": "Rank stocks by realized volatility and hold the calmest names under the shared risk gate.",
        "best_for": "Defensive positioning; may lag during sharp risk-on rallies.",
    },
)

GUIDED_BY_ID = {item["template_id"]: item for item in GUIDED_STRATEGIES}
GUIDED_BY_ID.update(
    {
        # Backward-compatible mappings for Battles created before Guided v2.
        "momentum_rank": {
            "template_id": "momentum_rank",
            "display_name": "Legacy Momentum Rank",
            "worker_strategy_id": "classic_30_stock_top3_momentum_v1",
        },
        "mean_reversion": {
            "template_id": "mean_reversion",
            "display_name": "Legacy Mean Reversion",
            "worker_strategy_id": "classic_30_stock_mean_reversion_v1",
        },
    }
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
            "strategy_mode": request.strategy_mode,
            "guided_strategy": (
                request.guided_strategy.canonical_payload()
                if request.guided_strategy is not None else None
            ),
            "custom_code": request.custom_code,
            "custom_code_hash": (
                code_digest(request.custom_code) if request.custom_code is not None else None
            ),
            "code_validation": None,
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

    def _comparison_items(self, battle: dict[str, Any]) -> list[dict[str, Any]]:
        if battle.get("strategy_mode", "guided") == "code":
            human = {
                "strategy_id": "human-code",
                "display_name": "Your Strategy: Custom LEAN Code",
                "family": "Human",
                "role": "human",
                "custom_code": battle["custom_code"],
            }
        else:
            guided = battle["guided_strategy"]
            template = GUIDED_BY_ID[guided["template_id"]]
            human = {
                "strategy_id": "human-guided",
                "worker_strategy_id": template["worker_strategy_id"],
                "display_name": f"Your Strategy: {template['display_name']}",
                "family": "Human",
                "role": "human",
                "lookback_days": int(guided["lookback_days"]),
            }
        baseline_items = [
            {
                **item,
                "worker_strategy_id": item["strategy_id"],
                "role": "baseline",
            }
            for item in BASELINES
        ]
        return [human, *baseline_items]

    def validate_custom_code(self, battle_id: str, code: str) -> dict[str, Any]:
        battle = self.repository.get_battle(battle_id)
        if battle is None:
            raise KeyError("Unknown battle_id")
        if battle.get("strategy_mode") != "code":
            raise ValueError("This Battle uses Guided Mode and has no custom code to admit")
        digest = code_digest(code)
        if digest != battle.get("custom_code_hash"):
            raise ValueError("Submitted code differs from the immutable code locked in this Battle")

        current = battle.get("code_validation") or {}
        if current.get("code_hash") == digest and current.get("smoke_status") in {
            "queued", "running", "completed"
        }:
            return self.refresh_custom_code_validation(battle_id)

        static = validate_user_code(code)
        validation = {
            "battle_id": battle_id,
            "code_hash": digest,
            "accepted": False,
            "checks": static["checks"],
            "errors": static["errors"],
            "smoke_status": "not_submitted",
            "smoke_run_id": None,
            "smoke_result_hash": None,
        }
        if not static["accepted"]:
            validation["smoke_status"] = "blocked_by_static_checks"
            self.repository.update_code_validation(battle_id, validation)
            return validation

        contract = battle["experiment_contract"]
        end = date.fromisoformat(contract["end_date"])
        start = max(date.fromisoformat(contract["start_date"]), end - timedelta(days=365))
        smoke_parameters = self._parameters(battle)
        smoke_parameters.update(
            {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "symbols": ",".join(contract["symbols"][:5]),
                "top_k": str(min(3, len(contract["symbols"][:5]))),
                "validation_mode": "smoke",
            }
        )
        try:
            submitted = self.worker.submit_custom(code, smoke_parameters, timeout_seconds=300)
            validation["smoke_status"] = submitted.get("state", "queued")
            validation["smoke_run_id"] = submitted["run_id"]
        except WorkerClientError as exc:
            validation["smoke_status"] = "failed"
            validation["errors"].append(str(exc))
        self.repository.update_code_validation(battle_id, validation)
        return validation

    def refresh_custom_code_validation(self, battle_id: str) -> dict[str, Any]:
        battle = self.repository.get_battle(battle_id)
        if battle is None:
            raise KeyError("Unknown battle_id")
        validation = battle.get("code_validation")
        if not validation:
            raise ValueError("No code admission has been submitted for this Battle")
        run_id = validation.get("smoke_run_id")
        if not run_id or validation.get("smoke_status") in TERMINAL_STATES:
            return validation
        try:
            worker_record = self.worker.job(run_id)
            state = worker_record.get("state", "failed")
            validation["smoke_status"] = state
            if state in TERMINAL_STATES:
                if state == "completed" and worker_record.get("result_path"):
                    result = self.worker.result(run_id)
                    validation["smoke_result_hash"] = result_digest(result)
                    validation["accepted"] = True
                    validation["checks"]["Isolated LEAN smoke"] = True
                else:
                    validation["accepted"] = False
                    validation["checks"]["Isolated LEAN smoke"] = False
                    error = worker_record.get("error") or f"LEAN smoke ended with state={state}"
                    if error not in validation["errors"]:
                        validation["errors"].append(error)
        except WorkerClientError as exc:
            validation["errors"].append(str(exc))
        self.repository.update_code_validation(battle_id, validation)
        return validation

    def run_baselines(self, battle_id: str) -> BaselineBatchView:
        battle = self.repository.get_battle(battle_id)
        if battle is None:
            raise KeyError("Unknown battle_id")
        if battle.get("strategy_mode") == "code":
            validation = battle.get("code_validation") or {}
            if not validation.get("accepted") or (
                validation.get("code_hash") != battle.get("custom_code_hash")
            ):
                raise ValueError(
                    "Custom code must pass static checks and the isolated LEAN smoke before full comparison"
                )
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
        comparison_items = self._comparison_items(battle)
        runs = [
            {
                "strategy_id": item["strategy_id"],
                "display_name": item["display_name"],
                "family": item["family"],
                "role": item["role"],
                "state": "submitting",
            }
            for item in comparison_items
        ]
        self.repository.create_batch(batch, runs)

        errors = []
        parameters = self._parameters(battle)
        for item in comparison_items:
            run_parameters = dict(parameters)
            if item["role"] == "human" and "lookback_days" in item:
                run_parameters["lookback"] = str(item["lookback_days"])
            try:
                if item["role"] == "human" and item.get("custom_code"):
                    submitted = self.worker.submit_custom(
                        item["custom_code"], run_parameters
                    )
                else:
                    submitted = self.worker.submit(
                        item["worker_strategy_id"], run_parameters
                    )
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

        state = "failed" if len(errors) == len(comparison_items) else "queued"
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
                    role=run.get("role", "baseline"),
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
