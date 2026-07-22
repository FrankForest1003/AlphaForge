from __future__ import annotations

import hmac
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.io_utils import atomic_write_text

CONFIG_PATH = Path(os.environ.get("ALPHAFORGE_WORKER_CONFIG", "/app/config/worker.json"))
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
RUNTIME_ROOT = Path(CONFIG["runtime_root"]).resolve()
STRATEGY_ROOT = Path(CONFIG["strategy_root"]).resolve()
DATA_ROOT = Path(CONFIG["data_folder"]).resolve()
CATALOG_ROOT = DATA_ROOT / "alphaforge-catalog"
UNIVERSE_PATH = Path(
    os.environ.get(
        "ALPHAFORGE_UNIVERSE_CONFIG",
        "/app/config/universe_whitelist_v1.0.json",
    )
)
API_TOKEN = os.environ.get("ALPHAFORGE_API_TOKEN", "")
JOB_INDEX = RUNTIME_ROOT / "service" / "jobs"
JOB_INDEX.mkdir(parents=True, exist_ok=True)
CUSTOM_SOURCE_ROOT = RUNTIME_ROOT / "service" / "custom_sources"
CUSTOM_SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
CUSTOM_EXPECTED_MARKER = "ALPHAFORGE_USER_STRATEGY_COMPLETED"

app = FastAPI(
    title="AlphaForge Local LEAN Runtime",
    description=(
        "Dockerized local LEAN backtesting API with 30-stock real-data support, "
        "machine learning, and detailed JSON output."
    ),
    version=os.environ.get("ALPHAFORGE_RUNTIME_VERSION", "1.1.3"),
)
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lean-job")
execution_lock = threading.Lock()


class SubmitRequest(BaseModel):
    strategy_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)


class CustomSubmitRequest(BaseModel):
    algorithm_code: str = Field(min_length=1, max_length=65_536)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def authorize(token: str | None) -> None:
    if API_TOKEN and (token is None or not hmac.compare_digest(token, API_TOKEN)):
        raise HTTPException(status_code=401, detail="Invalid worker token")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def data_status_payload() -> dict[str, Any]:
    manifest = read_json(CATALOG_ROOT / "dataset_manifest.json", {}) or {}
    quality = read_json(CATALOG_ROOT / "quality_report.json", {}) or {}
    universe = read_json(UNIVERSE_PATH, {}) or {}
    required = [
        str(item["lean_ticker"]).upper()
        for item in list(universe.get("tradable_symbols", []))
        + list(universe.get("analysis_dependencies", []))
        if item.get("lean_ticker")
    ]
    available = {
        str(item.get("ticker", "")).upper()
        for item in quality.get("symbols", [])
        if int(item.get("rows") or 0) > 0
    }
    missing = sorted(set(required).difference(available))
    ready = bool(manifest.get("ready")) and bool(quality.get("ready")) and not missing
    return {
        "ready": ready,
        "provider": manifest.get("provider"),
        "source": manifest.get("source"),
        "data_version": manifest.get("data_version"),
        "universe_id": manifest.get("universe_id") or universe.get("universe_id"),
        "required_symbol_count": len(required),
        "available_symbol_count": len(available.intersection(required)),
        "missing_symbols": missing,
        "common_end_date": manifest.get("common_end_date") or quality.get("common_end_date"),
        "requested_start_date": manifest.get("requested_start_date"),
        "downloaded_at_utc": manifest.get("downloaded_at_utc"),
        "normalization_policy": manifest.get("normalization_policy"),
        "security_master_policy": manifest.get("security_master_policy"),
        "failed_quality_symbols": quality.get("failed_quality_symbols", []),
        "provider_errors": quality.get("provider_errors", []),
        "catalog_files": {
            "dataset_manifest": str(CATALOG_ROOT / "dataset_manifest.json"),
            "quality_report": str(CATALOG_ROOT / "quality_report.json"),
            "availability": str(CATALOG_ROOT / "availability.csv"),
            "checksums": str(CATALOG_ROOT / "checksums.json"),
        },
    }


def load_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    registry_dir = STRATEGY_ROOT / "registry"
    for path in sorted(registry_dir.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        sid = item["strategy_id"]
        if sid in registry:
            raise RuntimeError(f"Duplicate strategy_id: {sid}")
        registry[sid] = item
    return registry


def resolve_entry(item: dict[str, Any]) -> Path:
    path = (STRATEGY_ROOT / item["entry_file"]).resolve()
    try:
        path.relative_to(STRATEGY_ROOT)
    except ValueError as exc:
        raise RuntimeError("Strategy entry escapes strategy_root") from exc
    if not path.is_file():
        raise RuntimeError(f"Strategy entry not found: {path}")
    return path


def record_path(run_id: str) -> Path:
    return JOB_INDEX / f"{run_id}.json"


def save_record(record: dict[str, Any]) -> None:
    atomic_write_text(
        record_path(record["run_id"]),
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_record(run_id: str) -> dict[str, Any] | None:
    return read_json(record_path(run_id))


def resolve_parameters(item: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(item.get("default_parameters", {}))
    parameters.update(overrides)
    end_date = str(parameters.get("end_date", "")).strip().lower()
    if end_date in {"latest", "auto", "today"}:
        status = data_status_payload()
        latest = status.get("common_end_date")
        if not latest:
            raise HTTPException(
                status_code=409,
                detail="No complete real-data end date is available. Run the data synchronization first.",
            )
        parameters["end_date"] = latest
    return parameters


def ensure_data_ready(item: dict[str, Any]) -> None:
    if not item.get("requires_real_data"):
        return
    status = data_status_payload()
    if not status["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The licensed 30-stock dataset is not ready",
                "data_status": status,
                "next_step": "Run scripts/data-sync.ps1 on Windows or scripts/data-sync.sh on macOS/Linux.",
            },
        )
    required = {str(symbol).upper() for symbol in item.get("required_symbols", [])}
    missing = sorted(required.intersection(set(status.get("missing_symbols", []))))
    if missing:
        raise HTTPException(
            status_code=409,
            detail={"message": "Required strategy data is missing", "symbols": missing},
        )


def validate_custom_envelope(code: str) -> None:
    """Defense in depth; the backend performs the authoritative AST admission."""
    required = (
        "class UserStrategy(AlphaForgeBaseAlgorithm)",
        "def initialize_strategy(",
        "def on_alpha_end(",
        CUSTOM_EXPECTED_MARKER,
    )
    missing = [value for value in required if value not in code]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "Custom strategy envelope is incomplete", "missing": missing},
        )
    forbidden = re.compile(
        r"(^|\W)(os|sys|subprocess|socket|pathlib|requests|urllib|open|exec|eval|__import__)\b"
    )
    match = forbidden.search(code)
    if match:
        raise HTTPException(
            status_code=422,
            detail=f"Custom strategy contains a blocked capability: {match.group(2)}",
        )


def custom_source(code: str) -> tuple[str, Path]:
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    path = (CUSTOM_SOURCE_ROOT / f"{digest}.py").resolve()
    path.relative_to(CUSTOM_SOURCE_ROOT)
    if path.is_file():
        if path.read_text(encoding="utf-8") != code:
            raise HTTPException(status_code=409, detail="Immutable source hash collision")
    else:
        path.write_text(code, encoding="utf-8")
    return digest, path


def execute(run_id: str) -> None:
    with execution_lock:
        record = read_record(run_id)
        if record is None:
            return
        try:
            if record.get("custom_algorithm_path"):
                algorithm = Path(record["custom_algorithm_path"]).resolve()
                algorithm.relative_to(CUSTOM_SOURCE_ROOT)
                if not algorithm.is_file():
                    raise RuntimeError("Immutable custom strategy source is missing")
                item = {
                    "algorithm_class": "UserStrategy",
                    "expected_marker": CUSTOM_EXPECTED_MARKER,
                }
            else:
                item = load_registry()[record["strategy_id"]]
                algorithm = resolve_entry(item)
            record["state"] = "running"
            record["started_at"] = now()
            save_record(record)

            command = [
                sys.executable,
                "/app/worker/run_job.py",
                "--worker-config",
                str(CONFIG_PATH),
                "--algorithm",
                str(algorithm),
                "--algorithm-class",
                item["algorithm_class"],
                "--run-id",
                run_id,
                "--timeout-seconds",
                str(record["timeout_seconds"]),
                "--parameters-json",
                json.dumps(record["parameters"], ensure_ascii=False),
            ]
            if item.get("expected_marker"):
                command.extend(["--expected-marker", item["expected_marker"]])

            process = subprocess.run(
                command,
                cwd="/app",
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )

            result_path = RUNTIME_ROOT / "results" / run_id / "result.json"
            console_path = RUNTIME_ROOT / "results" / run_id / "console.log"
            if result_path.is_file():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                record["state"] = result["status"]
                record["result_path"] = str(result_path)
                record["log_path"] = str(console_path)
            else:
                record["state"] = "failed"
                record["error"] = (
                    f"Runner exit={process.returncode}\n"
                    f"STDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"
                )
        except Exception as exc:
            record["state"] = "failed"
            record["error"] = str(exc)
        finally:
            record["finished_at"] = now()
            save_record(record)


@app.get("/health")
def health() -> dict[str, Any]:
    launcher = Path(CONFIG["lean_root"]) / "Launcher/bin/Release/QuantConnect.Lean.Launcher.dll"
    checks = {
        "lean_root": Path(CONFIG["lean_root"]).exists(),
        "launcher": launcher.is_file(),
        "data_folder": DATA_ROOT.is_dir(),
        "strategy_root": STRATEGY_ROOT.is_dir(),
        "dotnet": Path(CONFIG["dotnet_executable"]).is_file(),
    }
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "version": app.version,
        "checks": checks,
        "real_data_ready": data_status_payload()["ready"],
    }


@app.get("/v1/data/status")
def data_status(x_worker_token: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(x_worker_token)
    return data_status_payload()


@app.get("/v1/universes/default")
def default_universe(x_worker_token: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(x_worker_token)
    universe = read_json(UNIVERSE_PATH)
    if universe is None:
        raise HTTPException(status_code=500, detail="Default universe configuration is missing")
    return universe


@app.get("/v1/strategies")
def strategies(x_worker_token: str | None = Header(default=None)) -> list[dict[str, Any]]:
    authorize(x_worker_token)
    return list(load_registry().values())


@app.get("/v1/jobs")
def jobs(
    limit: int = Query(default=50, ge=1, le=500),
    x_worker_token: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    authorize(x_worker_token)
    records = []
    for path in JOB_INDEX.glob("*.json"):
        record = read_json(path)
        if record:
            records.append(record)
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return records[:limit]


@app.post("/v1/jobs", status_code=202)
def submit(request: SubmitRequest, x_worker_token: str | None = Header(default=None)) -> dict[str, str]:
    authorize(x_worker_token)
    registry = load_registry()
    if request.strategy_id not in registry:
        raise HTTPException(status_code=400, detail="Unknown strategy_id")
    item = registry[request.strategy_id]
    resolve_entry(item)
    ensure_data_ready(item)
    parameters = resolve_parameters(item, request.parameters)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    record = {
        "run_id": run_id,
        "strategy_id": request.strategy_id,
        "state": "queued",
        "created_at": now(),
        "started_at": None,
        "finished_at": None,
        "timeout_seconds": request.timeout_seconds
        or int(CONFIG.get("default_timeout_seconds", 1800)),
        "parameters": parameters,
        "result_path": None,
        "log_path": None,
        "error": None,
    }
    save_record(record)
    executor.submit(execute, run_id)
    return {"run_id": run_id, "state": "queued", "strategy_id": request.strategy_id}


@app.post("/v1/custom-jobs", status_code=202)
def submit_custom(
    request: CustomSubmitRequest,
    x_worker_token: str | None = Header(default=None),
) -> dict[str, str]:
    authorize(x_worker_token)
    validate_custom_envelope(request.algorithm_code)
    symbols = [
        value.strip().upper()
        for value in str(request.parameters.get("symbols", "")).split(",")
        if value.strip()
    ]
    item = {
        "requires_real_data": True,
        "required_symbols": [*symbols, "SPY", "QQQ"],
        "default_parameters": {},
    }
    ensure_data_ready(item)
    parameters = resolve_parameters(item, request.parameters)
    digest, source_path = custom_source(request.algorithm_code)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    strategy_id = f"custom:{digest[:12]}"
    record = {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "source_hash": digest,
        "custom_algorithm_path": str(source_path),
        "state": "queued",
        "created_at": now(),
        "started_at": None,
        "finished_at": None,
        "timeout_seconds": request.timeout_seconds
        or int(CONFIG.get("default_timeout_seconds", 1800)),
        "parameters": parameters,
        "result_path": None,
        "log_path": None,
        "error": None,
    }
    save_record(record)
    executor.submit(execute, run_id)
    return {"run_id": run_id, "state": "queued", "strategy_id": strategy_id}


@app.get("/v1/jobs/{run_id}")
def job(run_id: str, x_worker_token: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(x_worker_token)
    record = read_record(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return record


@app.get("/v1/jobs/{run_id}/result")
def result(run_id: str, x_worker_token: str | None = Header(default=None)):
    authorize(x_worker_token)
    record = read_record(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    path = Path(record.get("result_path") or "")
    if not path.is_file():
        raise HTTPException(status_code=409, detail="Result is not ready")
    return FileResponse(path, media_type="application/json", filename=f"{run_id}-result.json")


@app.get("/v1/jobs/{run_id}/artifacts")
def artifacts(run_id: str, x_worker_token: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(x_worker_token)
    result_dir = (RUNTIME_ROOT / "results" / run_id).resolve()
    if not result_dir.is_dir():
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return {
        "run_id": run_id,
        "files": [
            {"name": path.name, "size_bytes": path.stat().st_size}
            for path in sorted(result_dir.iterdir())
            if path.is_file()
        ],
    }


@app.get("/v1/jobs/{run_id}/artifacts/{name}")
def artifact(
    run_id: str,
    name: str,
    x_worker_token: str | None = Header(default=None),
):
    authorize(x_worker_token)
    result_dir = (RUNTIME_ROOT / "results" / run_id).resolve()
    path = (result_dir / name).resolve()
    try:
        path.relative_to(result_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact path") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path, filename=path.name)
