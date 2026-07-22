from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_settings
from app.repositories import SQLiteRepository
from app.schemas import (
    BaselineBatchView,
    BattleCreate,
    BattleView,
    CodeValidationRequest,
    CodeValidationView,
)
from app.services import BaselineService, LeanWorkerClient, WorkerClientError
from app.services.baseline_service import BASELINES, GUIDED_STRATEGIES


settings = load_settings()
universe = json.loads(settings.universe_path.read_text(encoding="utf-8"))
allowed_symbols = {
    str(item["display_ticker"]).upper()
    for item in universe.get("tradable_symbols", [])
}
repository = SQLiteRepository(settings.database_path)
worker = LeanWorkerClient(settings.worker_base_url, settings.worker_token)
service = BaselineService(repository, worker, allowed_symbols)

app = FastAPI(
    title="AlphaForge Platform API",
    version="0.1.0",
    description="Immutable battle contracts and real LEAN public-baseline orchestration.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/v1/health")
def health() -> dict[str, Any]:
    try:
        worker_health = worker.health()
        worker_status = worker_health.get("status", "unknown")
    except WorkerClientError as exc:
        worker_health = {"status": "unavailable", "error": str(exc)}
        worker_status = "unavailable"
    return {
        "status": "ok" if worker_status == "ok" else "degraded",
        "backend": "healthy",
        "database": str(settings.database_path),
        "lean_worker": worker_health,
        "agent_runtime": "not_configured",
    }


@app.get("/v1/catalog/universe")
def catalog_universe() -> dict[str, Any]:
    return {
        **universe,
        "minimum_selectable": 5,
        "maximum_selectable": 30,
        "default_symbols": [
            item["display_ticker"] for item in universe.get("tradable_symbols", [])
        ],
    }


@app.get("/v1/catalog/baselines")
def catalog_baselines() -> list[dict[str, Any]]:
    return list(BASELINES)


@app.get("/v1/catalog/guided-strategies")
def catalog_guided_strategies() -> list[dict[str, Any]]:
    """Return the only Human templates admitted to the current guided flow."""
    return [
        {key: value for key, value in item.items() if key != "worker_strategy_id"}
        for item in GUIDED_STRATEGIES
    ]


@app.post(
    "/v1/battles",
    response_model=BattleView,
    status_code=status.HTTP_201_CREATED,
)
def create_battle(request: BattleCreate) -> BattleView:
    try:
        return service.create_battle(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/battles/{battle_id}", response_model=BattleView)
def get_battle(battle_id: str) -> BattleView:
    battle = service.get_battle(battle_id)
    if battle is None:
        raise HTTPException(status_code=404, detail="Unknown battle_id")
    return battle


@app.post(
    "/v1/battles/{battle_id}/baselines/run",
    response_model=BaselineBatchView,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_baselines(battle_id: str) -> BaselineBatchView:
    try:
        return service.run_baselines(battle_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/strategies/code/validate", response_model=CodeValidationView)
def validate_code(request: CodeValidationRequest) -> dict[str, Any]:
    try:
        return service.validate_custom_code(request.battle_id, request.code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/v1/strategies/code/validate/{battle_id}",
    response_model=CodeValidationView,
)
def get_code_validation(battle_id: str) -> dict[str, Any]:
    try:
        return service.refresh_custom_code_validation(battle_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/v1/battles/{battle_id}/baselines",
    response_model=BaselineBatchView | None,
)
def get_latest_baselines(
    battle_id: str,
    refresh: bool = Query(default=True),
) -> BaselineBatchView | None:
    try:
        return service.latest_batch(battle_id, refresh=refresh)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/baseline-batches/{batch_id}", response_model=BaselineBatchView)
def get_baseline_batch(batch_id: str) -> BaselineBatchView:
    try:
        return service.refresh_batch(batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/battles/{battle_id}/rounds/{round_id}/ai-forge")
def ai_forge_not_configured(battle_id: str, round_id: str):
    if service.get_battle(battle_id) is None:
        raise HTTPException(status_code=404, detail="Unknown battle_id")
    raise HTTPException(
        status_code=501,
        detail={
            "code": "agent_runtime_not_configured",
            "message": "AI Forge is reserved for the member-D Agent Runtime integration.",
            "round_id": round_id,
        },
    )
