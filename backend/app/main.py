from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from agent import (
    DeepSeekCritic,
    DeepSeekDesigner,
    DeepSeekEducator,
)
from app.config import load_settings
from app.schemas import ForgeRunRequest, RobustnessRunRequest
from app.services import (
    BASELINES,
    ForgeService,
    LeanWorkerPoolClient,
    WorkerClientError,
)


settings = load_settings()
universe = json.loads(settings.universe_path.read_text(encoding="utf-8"))
tradable_symbols = {
    str(item["display_ticker"]).upper()
    for item in universe.get("tradable_symbols", [])
}
benchmarks = {
    str(item["display_ticker"]).upper()
    for item in universe.get("analysis_dependencies", [])
    if item.get("role") == "benchmark"
}
worker = LeanWorkerPoolClient.from_urls(
    settings.worker_urls,
    settings.worker_token,
)
agent_options = {
    "api_key": settings.api_key,
    "base_url": settings.base_url,
    "model": settings.model,
    "thinking_enabled": settings.thinking_enabled,
}
designer = DeepSeekDesigner(**agent_options)
critic = DeepSeekCritic(**agent_options)
educator = DeepSeekEducator(**agent_options)
forge = ForgeService(
    worker=worker,
    designer=designer,
    critic=critic,
    educator=educator,
    allowed_symbols=tradable_symbols,
    allowed_benchmarks=benchmarks,
    trace_root=settings.trace_root,
    history_root=settings.history_root,
)

app = FastAPI(
    title="AlphaForge API",
    version="1.0.0",
    description=(
        "Four public baselines, one Human strategy, and three parallel "
        "DeepSeek-designed parameter strategies compiled into a fixed LEAN template."
    ),
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
    except WorkerClientError as exc:
        worker_health = {"status": "unavailable", "error": str(exc)}
    healthy = worker_health.get("status") == "ok"
    return {
        "status": "ok" if healthy else "degraded",
        "worker": worker_health,
        "designer": designer.health(),
        "critic": critic.health(),
        "educator": educator.health(),
    }


@app.get("/v1/catalog/universe")
def catalog_universe() -> dict[str, Any]:
    return {
        "tradable_symbols": universe.get("tradable_symbols", []),
        "benchmarks": sorted(benchmarks),
        "default_symbols": ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
    }


@app.get("/v1/catalog/baselines")
def catalog_baselines() -> list[dict[str, str]]:
    return [
        {"name": item["name"], "family": item["family"]}
        for item in BASELINES
    ]


@app.post(
    "/v1/forge-runs",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_forge_run(request: ForgeRunRequest) -> dict[str, Any]:
    try:
        return forge.create(request.settings, request.human_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/forge-runs/{run_id}")
def get_forge_run(run_id: str) -> dict[str, Any]:
    run = forge.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return run


@app.post(
    "/v1/forge-runs/{run_id}/robustness",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_robustness_run(
    run_id: str,
    request: RobustnessRunRequest,
) -> dict[str, Any]:
    try:
        return forge.start_robustness(run_id, request.target)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/forge-history")
def list_forge_history() -> list[dict[str, Any]]:
    return forge.list_history(limit=5)


@app.get("/v1/forge-history/{run_id}")
def get_forge_history(run_id: str) -> dict[str, Any]:
    record = forge.get_history(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown historical run_id")
    return record


@app.get("/v1/forge-runs/{run_id}/trace")
def get_forge_run_trace(run_id: str) -> dict[str, Any]:
    trace = forge.get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="unknown run_id trace")
    return trace
