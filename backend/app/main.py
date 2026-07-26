from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent import (
    DeepSeekCritic,
    DeepSeekDesigner,
    DeepSeekEducator,
    DeepSeekRoundCoach,
)
from app.config import load_settings
from app.repositories import SQLiteGameRepository
from app.schemas import (
    BattleCreateRequest,
    CredentialsRequest,
    ForgeRunRequest,
    RobustnessRunRequest,
)
from app.services import (
    BASELINES,
    ForgeService,
    LeanWorkerPoolClient,
    WorkerClientError,
)


# Application composition root: construct long-lived adapters once and inject
# them into ForgeService. Request handlers below remain thin transport boundaries.
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
coach = DeepSeekRoundCoach(**agent_options)
games = SQLiteGameRepository(settings.database_path)
forge = ForgeService(
    worker=worker,
    designer=designer,
    critic=critic,
    educator=educator,
    allowed_symbols=tradable_symbols,
    allowed_benchmarks=benchmarks,
    trace_root=settings.trace_root,
    history_root=settings.history_root,
    coach=coach,
    game_repository=games,
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
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
bearer = HTTPBearer(auto_error=False)


def optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any] | None:
    """Resolve identity when present while preserving anonymous standalone runs."""

    if credentials is None:
        return None
    return games.user_from_token(credentials.credentials)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict[str, Any]:
    """Require a valid session for user-owned battle resources."""

    user = (
        games.user_from_token(credentials.credentials)
        if credentials is not None
        else None
    )
    if user is None:
        raise HTTPException(status_code=401, detail="sign in to continue")
    return user


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
        "coach": coach.health(),
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


def _auth_response(user: dict[str, Any]) -> dict[str, Any]:
    return {"token": games.create_session(user["id"]), "user": user}


@app.post("/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register(request: CredentialsRequest) -> dict[str, Any]:
    try:
        return _auth_response(games.create_user(request.username, request.password))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/auth/login")
def login(request: CredentialsRequest) -> dict[str, Any]:
    user = games.authenticate(request.username, request.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    return _auth_response(user)


@app.get("/v1/auth/me")
def auth_me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user


@app.post("/v1/auth/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict[str, bool]:
    if credentials is not None:
        games.revoke_session(credentials.credentials)
    return {"signed_out": True}


@app.get("/v1/battles")
def list_battles(
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    return games.list_battles(user["id"])


@app.post("/v1/battles", status_code=status.HTTP_201_CREATED)
def create_battle(
    request: BattleCreateRequest,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return games.create_battle(user["id"], request.name)


@app.get("/v1/battles/{battle_id}")
def get_battle(
    battle_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    try:
        return games.get_battle(user["id"], battle_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/v1/battles/{battle_id}")
def delete_battle(
    battle_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    try:
        games.delete_battle(user["id"], battle_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True}


def authorize_run(
    run_id: str,
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    """Hide battle-owned run existence from users outside that battle."""

    run = forge.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    if run.get("battle_id"):
        if user is None:
            raise HTTPException(status_code=401, detail="sign in to view this round")
        try:
            games.get_battle(user["id"], run["battle_id"])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="unknown run_id") from exc
    return run


@app.post(
    "/v1/forge-runs",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_forge_run(
    request: ForgeRunRequest,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    try:
        if request.battle_id is not None and user is None:
            raise HTTPException(status_code=401, detail="sign in to start a battle round")
        return forge.create(
            request.settings,
            request.human_strategy,
            battle_id=request.battle_id,
            user_id=user["id"] if user else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/forge-runs/{run_id}")
def get_forge_run(
    run_id: str,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    return authorize_run(run_id, user)


@app.post(
    "/v1/forge-runs/{run_id}/robustness",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_robustness_run(
    run_id: str,
    request: RobustnessRunRequest,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    try:
        authorize_run(run_id, user)
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
def get_forge_run_trace(
    run_id: str,
    user: dict[str, Any] | None = Depends(optional_user),
) -> dict[str, Any]:
    authorize_run(run_id, user)
    trace = forge.get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="unknown run_id trace")
    return trace
