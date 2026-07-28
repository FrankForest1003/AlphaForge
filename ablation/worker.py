from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.services.baseline_service import (
    build_behavior_evidence,
    build_performance_analysis,
)
from app.services.strategy_template import compile_strategy_source, validate_strategy_spec
from app.services.worker_client import LeanWorkerPoolClient
from app.services.worker_client import WorkerClientError


TERMINAL_STATES = {"completed", "completed_with_data_gaps", "failed", "timeout"}


@dataclass
class WorkerArtifact:
    worker_run_id: str
    state: str
    result: dict[str, Any]
    details: dict[str, Any]
    behavior_evidence: dict[str, Any]
    analysis: dict[str, Any]
    console_log: str
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def worker_pool() -> LeanWorkerPoolClient:
    raw_urls = (
        os.getenv("ABLATION_WORKER_URLS")
        or os.getenv("ALPHAFORGE_WORKER_URLS")
        or os.getenv("ALPHAFORGE_WORKER_URL")
        or "http://127.0.0.1:18081"
    )
    urls = [item.strip().rstrip("/") for item in raw_urls.split(",") if item.strip()]
    token = os.getenv("ALPHAFORGE_WORKER_TOKEN") or os.getenv(
        "ALPHAFORGE_API_TOKEN",
        "local-dev-token",
    )
    return LeanWorkerPoolClient.from_urls(urls, token=token, timeout=30.0)


class WorkerExecutor:
    def __init__(
        self,
        pool: LeanWorkerPoolClient | None = None,
        *,
        poll_seconds: float = 2.0,
        timeout_seconds: int = 1_800,
    ) -> None:
        self.pool = pool or worker_pool()
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def run_spec(
        self,
        strategy_spec: dict[str, Any],
        parameters: dict[str, str],
    ) -> WorkerArtifact:
        validated = validate_strategy_spec(strategy_spec)
        return self.run_source(compile_strategy_source(validated), parameters)

    def run_source(
        self,
        source_code: str,
        parameters: dict[str, str],
    ) -> WorkerArtifact:
        started = time.monotonic()
        submitted = self.pool.submit_custom(
            source_code,
            parameters,
            timeout_seconds=self.timeout_seconds,
        )
        run_id = str(submitted["run_id"])
        state = "queued"
        record: dict[str, Any] = {}
        transient_unknown_run_attempts = 0
        while time.monotonic() - started <= self.timeout_seconds + 60:
            try:
                record = self.pool.job(run_id)
            except WorkerClientError as exc:
                if not exc.is_unknown_run or transient_unknown_run_attempts >= 4:
                    raise
                time.sleep(0.25 * (2**transient_unknown_run_attempts))
                transient_unknown_run_attempts += 1
                continue
            state = str(record.get("state") or "failed")
            if state in TERMINAL_STATES:
                break
            time.sleep(self.poll_seconds)
        else:
            raise TimeoutError(f"Ablation Worker polling timed out: {run_id}")

        if "result_path" in record and not record.get("result_path"):
            raise RuntimeError(
                str(record.get("error") or f"Worker finished with state={state}")
            )
        result = self.pool.result(run_id)
        try:
            console_log = self.pool.log(run_id)
        except Exception:
            console_log = ""
        details: dict[str, Any] = {}
        behavior: dict[str, Any] = {}
        analysis: dict[str, Any] = {}
        if result.get("status") == "completed":
            try:
                details = self.pool.details(run_id)
                behavior = build_behavior_evidence(details)
                analysis = build_performance_analysis(
                    details,
                    result.get("summary") or {},
                    initial_cash=float(parameters["initial_cash"]),
                )
            except Exception as exc:
                details = {"collection_error": str(exc)}
        return WorkerArtifact(
            worker_run_id=run_id,
            state=state,
            result=result,
            details=details,
            behavior_evidence=behavior,
            analysis=analysis,
            console_log=console_log,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
