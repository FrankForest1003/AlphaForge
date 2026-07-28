from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .config import StudyConfig
from .io import relative_artifact, write_json
from .manifest import ManifestStore
from .provider import generate_proposal


ARM_PROVIDER_NAMES = {
    "current": "full",
    "thinking_off": "no_thinking",
    "no_valid_example": "no_example",
    "no_retry": "no_retry",
}


def _attempt_count(trace: dict[str, Any]) -> int:
    semantic = trace.get("semantic_validation_attempts") or []
    if semantic:
        return sum(len((item.get("call") or {}).get("attempts") or []) for item in semantic)
    return len(trace.get("attempts") or [])


def _usage(proposal: dict[str, Any]) -> dict[str, int]:
    usage = proposal.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
        "llm_attempts": _attempt_count(proposal.get("trace") or {}),
        "lean_jobs": 0,
    }


def register_reliability_units(store: ManifestStore, study: StudyConfig) -> None:
    store.register_units(
        {
            "id": f"{arm.id}/{replicate}/{track}",
            "arm": arm.id,
            "replicate": replicate,
            "track": track,
            "stage": "designer",
            "external_call": True,
        }
        for arm in study.arms
        for replicate in range(1, study.replicates + 1)
        for track in study.tracks
    )


def run_reliability(store: ManifestStore, study: StudyConfig) -> None:
    register_reliability_units(store, study)
    pending = {item["id"] for item in store.pending_units()}
    for arm in study.arms:
        provider_arm = ARM_PROVIDER_NAMES[arm.id]
        for replicate in range(1, study.replicates + 1):
            tasks = [
                track
                for track in study.tracks
                if f"{arm.id}/{replicate}/{track}" in pending
            ]
            if not tasks:
                continue
            with ThreadPoolExecutor(
                max_workers=min(study.max_parallel_tracks, len(tasks))
            ) as executor:
                futures = {
                    executor.submit(
                        _run_one,
                        store,
                        study,
                        arm.id,
                        provider_arm,
                        replicate,
                        track,
                    ): track
                    for track in tasks
                }
                for future in as_completed(futures):
                    future.result()


def _run_one(
    store: ManifestStore,
    study: StudyConfig,
    arm: str,
    provider_arm: str,
    replicate: int,
    track: str,
) -> None:
    unit_id = f"{arm}/{replicate}/{track}"
    store.start_unit(unit_id)
    started = time.perf_counter()
    target = store.experiment_dir / "arms" / arm / str(replicate) / f"{track}.json"
    try:
        proposal = generate_proposal(
            arm=provider_arm,
            track=track,
            run_settings=dict(study.run_settings),
            baseline_results=[],
        )
        trace = proposal.get("trace") or {}
        spec = proposal["strategy_spec"]
        artifact = {
            "status": "passed",
            "arm": arm,
            "replicate": replicate,
            "track": track,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "first_schema_pass": int(trace.get("semantic_retry_count", 0) or 0) == 0,
            "semantic_retry_count": int(trace.get("semantic_retry_count", 0) or 0),
            "api_attempts": _attempt_count(trace),
            "strategy_spec_sha256": hashlib.sha256(
                json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "proposal": {"design": proposal["design"], "strategy_spec": spec},
            "usage": proposal.get("usage") or {},
            "trace": trace,
        }
        write_json(target, artifact)
        store.complete_unit(
            unit_id,
            artifact=relative_artifact(target, store.experiment_dir),
            usage=_usage(proposal),
        )
    except Exception as exc:
        trace = getattr(exc, "trace", {}) or {}
        artifact = {
            "status": "failed",
            "arm": arm,
            "replicate": replicate,
            "track": track,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "api_attempts": _attempt_count(trace),
            "trace": trace,
        }
        write_json(target, artifact)
        store.fail_unit(
            unit_id,
            str(exc),
            artifact=relative_artifact(target, store.experiment_dir),
        )
