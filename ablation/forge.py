from __future__ import annotations

import copy
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from app.schemas import RunSettings
from app.schemas.agent_strategy import compact_iteration_result
from app.services.strategy_template import compile_strategy_source

from .config import StudyConfig
from .io import read_json, relative_artifact, write_json
from .manifest import ManifestStore
from .provider import critic, generate_proposal
from .worker import WorkerExecutor


def _add_usage(total: dict[str, int], value: dict[str, Any], *, calls: int = 1) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] += int(value.get(key, 0) or 0)
    total["llm_attempts"] += calls


def _trace_attempt_count(trace: dict[str, Any]) -> int:
    semantic = trace.get("semantic_validation_attempts") or []
    if semantic:
        count = sum(
            len((item.get("call") or {}).get("attempts") or [])
            for item in semantic
        )
        return count or 1
    return len(trace.get("attempts") or []) or 1


def _selection_key(iteration: dict[str, Any]) -> tuple[float, float, float]:
    summary = iteration.get("summary") or {}
    def number(name: str, default: float) -> float:
        try:
            value = float(summary.get(name))
            return value if value == value else default
        except (TypeError, ValueError):
            return default
    return (number("sharpe_ratio", -1e12), number("cagr", -1e12), -number("maximum_drawdown", 1e12))


def _compact(number: int, worker: dict[str, Any]) -> dict[str, Any]:
    result = worker.get("result") or {}
    return compact_iteration_result(
        iteration=number,
        summary=result.get("summary") or {},
        analysis=worker.get("analysis") or {},
        behavior_evidence=worker.get("behavior_evidence") or {},
    )


def _iteration(number: int, proposal: dict[str, Any], worker: dict[str, Any]) -> dict[str, Any]:
    spec = proposal["strategy_spec"]
    source = compile_strategy_source(spec)
    return {
        "iteration": number,
        "status": "completed" if (worker.get("result") or {}).get("status") == "completed" else "failed",
        "design": proposal["design"],
        "strategy_spec": spec,
        "strategy_spec_sha256": hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "source_code": source,
        "summary": (worker.get("result") or {}).get("summary") or {},
        "analysis": worker.get("analysis") or {},
        "behavior_evidence": worker.get("behavior_evidence") or {},
        "worker": worker,
        "designer_usage": proposal.get("usage") or {},
        "designer_trace": proposal.get("trace") or {},
        "generation_retries": proposal.get("generation_retries", 0),
        "critique": None,
    }


def register_forge_units(store: ManifestStore, study: StudyConfig) -> None:
    units = []
    for replicate in range(1, study.replicates + 1):
        for track in study.tracks:
            units.append({
                "id": f"shared/{replicate}/{track}", "arm": "shared", "replicate": replicate,
                "track": track, "stage": "initial_and_worker", "external_call": True,
            })
            for arm in ("full", "no_critic", "no_baseline_context"):
                units.append({
                    "id": f"{arm}/{replicate}/{track}", "arm": arm, "replicate": replicate,
                    "track": track, "stage": "pipeline", "external_call": True,
                })
    store.register_units(units)


def run_forge(
    store: ManifestStore,
    study: StudyConfig,
    baseline_results: list[dict[str, Any]],
    *,
    worker_factory: Callable[[], WorkerExecutor] | None = None,
) -> None:
    register_forge_units(store, study)
    if worker_factory is None:
        # One shared pool owns the active-job counters. Creating a pool per track
        # would make every track select slot one and only appear to be parallel.
        shared_worker = WorkerExecutor(
            poll_seconds=float(study.execution.get("worker_poll_seconds", 2.0)),
            timeout_seconds=int(study.execution.get("worker_timeout_seconds", 1800)),
        )
        factory: Callable[[], WorkerExecutor] = lambda: shared_worker
    else:
        factory = worker_factory
    settings = RunSettings.model_validate(dict(study.run_settings))
    parameters = settings.worker_parameters()
    arm_ids = {arm.id for arm in study.arms}
    for replicate in range(1, study.replicates + 1):
        _parallel_tracks(
            study,
            lambda track: _ensure_shared(store, study, baseline_results, parameters, factory, replicate, track),
        )
        for arm in ("full", "no_critic", "no_baseline_context"):
            if arm not in arm_ids:
                continue
            _parallel_tracks(
                study,
                lambda track, selected=arm: _ensure_branch(
                    store, study, baseline_results, parameters, factory, replicate, track, selected
                ),
            )


def _parallel_tracks(study: StudyConfig, operation: Callable[[str], None]) -> None:
    with ThreadPoolExecutor(max_workers=study.max_parallel_tracks) as executor:
        futures = {executor.submit(operation, track): track for track in study.tracks}
        for future in as_completed(futures):
            future.result()


def _ensure_shared(
    store: ManifestStore,
    study: StudyConfig,
    baselines: list[dict[str, Any]],
    parameters: dict[str, str],
    worker_factory: Callable[[], WorkerExecutor],
    replicate: int,
    track: str,
) -> None:
    unit_id = f"shared/{replicate}/{track}"
    unit = store.read()["units"][unit_id]
    if unit["status"] == "completed":
        return
    store.start_unit(unit_id)
    target = store.experiment_dir / "shared" / str(replicate) / f"{track}.json"
    started = time.perf_counter()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "llm_attempts": 0, "lean_jobs": 0}
    try:
        proposal = generate_proposal(
            arm="full", track=track, run_settings=dict(study.run_settings), baseline_results=baselines
        )
        _add_usage(
            usage,
            proposal.get("usage") or {},
            calls=_trace_attempt_count(proposal.get("trace") or {}),
        )
        worker = worker_factory().run_spec(proposal["strategy_spec"], parameters).to_dict()
        usage["lean_jobs"] = 1
        artifact = {
            "arm": "shared", "replicate": replicate, "track": track,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "iterations": [_iteration(1, proposal, worker)], "usage": usage,
        }
        write_json(target, artifact)
        store.complete_unit(unit_id, artifact=relative_artifact(target, store.experiment_dir), usage=usage)
    except Exception as exc:
        write_json(target, {"status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}})
        store.fail_unit(unit_id, str(exc), artifact=relative_artifact(target, store.experiment_dir))


def _ensure_branch(
    store: ManifestStore,
    study: StudyConfig,
    baselines: list[dict[str, Any]],
    parameters: dict[str, str],
    worker_factory: Callable[[], WorkerExecutor],
    replicate: int,
    track: str,
    arm: str,
) -> None:
    unit_id = f"{arm}/{replicate}/{track}"
    unit = store.read()["units"][unit_id]
    if unit["status"] == "completed":
        return
    shared = store.read()["units"][f"shared/{replicate}/{track}"]
    if arm != "no_baseline_context" and shared["status"] != "completed":
        if unit["status"] != "failed":
            store.fail_unit(unit_id, "shared iteration one did not complete")
        return
    store.start_unit(unit_id)
    target = store.experiment_dir / "arms" / arm / str(replicate) / f"{track}.json"
    started = time.perf_counter()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "llm_attempts": 0, "lean_jobs": 0}
    try:
        if arm == "no_baseline_context":
            proposal = generate_proposal(
                arm="full", track=track, run_settings=dict(study.run_settings), baseline_results=[]
            )
            _add_usage(
                usage,
                proposal.get("usage") or {},
                calls=_trace_attempt_count(proposal.get("trace") or {}),
            )
            worker = worker_factory().run_spec(proposal["strategy_spec"], parameters).to_dict()
            usage["lean_jobs"] += 1
            iterations = [_iteration(1, proposal, worker)]
            context_baselines: list[dict[str, Any]] = []
        else:
            shared_artifact = read_json(store.experiment_dir / shared["artifact"])
            iterations = copy.deepcopy(shared_artifact["iterations"])
            context_baselines = baselines
            shared_usage = shared_artifact.get("usage") or {}

        critic_enabled = arm != "no_critic"
        for number in range(1, 4):
            current = iterations[-1]
            if current["status"] != "completed":
                break
            prior_compact = [_compact(item["iteration"], item["worker"]) for item in iterations[:-1]]
            critique_report = None
            if critic_enabled:
                evaluated = critic().evaluate(
                    track=track,
                    iteration=number,
                    strategy_spec=current["strategy_spec"],
                    iteration_result=_compact(number, current["worker"]),
                    baseline_results=context_baselines,
                    iteration_history=prior_compact,
                )
                _add_usage(
                    usage,
                    evaluated.get("usage") or {},
                    calls=_trace_attempt_count(evaluated.get("trace") or {}),
                )
                critique_report = evaluated["report"]
                current["critique"] = critique_report
                current["critic_usage"] = evaluated.get("usage") or {}
                current["critic_trace"] = evaluated.get("trace") or {}
                current["discarded_recommendations"] = evaluated.get("discarded_recommendations") or []
            if number == 3:
                break
            proposal = generate_proposal(
                arm="full",
                track=track,
                run_settings=dict(study.run_settings),
                baseline_results=context_baselines,
                iteration=number + 1,
                previous_spec=current["strategy_spec"],
                critique=critique_report,
                iteration_history=[_compact(item["iteration"], item["worker"]) for item in iterations],
            )
            _add_usage(
                usage,
                proposal.get("usage") or {},
                calls=_trace_attempt_count(proposal.get("trace") or {}),
            )
            worker = worker_factory().run_spec(proposal["strategy_spec"], parameters).to_dict()
            usage["lean_jobs"] += 1
            iterations.append(_iteration(number + 1, proposal, worker))

        completed = [item for item in iterations if item["status"] == "completed"]
        best = max(completed, key=_selection_key) if completed else None
        effective_usage = dict(usage)
        effective_elapsed_seconds = round(time.perf_counter() - started, 3)
        if arm != "no_baseline_context":
            for key in effective_usage:
                effective_usage[key] += int(shared_usage.get(key, 0) or 0)
            effective_elapsed_seconds += float(shared_artifact.get("elapsed_seconds", 0) or 0)
        artifact = {
            "arm": arm, "replicate": replicate, "track": track,
            "status": "completed" if completed else "failed",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "effective_elapsed_seconds": round(effective_elapsed_seconds, 3),
            "shared_iteration_one": arm != "no_baseline_context",
            "baseline_context": arm != "no_baseline_context",
            "critic_enabled": critic_enabled,
            "iterations": iterations,
            "best_iteration": best["iteration"] if best else None,
            "best_summary": best["summary"] if best else {},
            "best_analysis": best["analysis"] if best else {},
            "best_behavior_evidence": best["behavior_evidence"] if best else {},
            "usage": usage,
            "effective_usage": effective_usage,
        }
        write_json(target, artifact)
        store.complete_unit(unit_id, artifact=relative_artifact(target, store.experiment_dir), usage=usage)
    except Exception as exc:
        write_json(target, {
            "status": "failed", "arm": arm, "replicate": replicate, "track": track,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "error": {"type": type(exc).__name__, "message": str(exc)}, "usage": usage,
        })
        store.fail_unit(unit_id, str(exc), artifact=relative_artifact(target, store.experiment_dir))


def load_frozen_baselines(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    record = read_json(path)
    baselines = record.get("baselines") or []
    completed = [item for item in baselines if item.get("state") == "completed"]
    if len(completed) < 4:
        raise ValueError("baseline history must contain four completed public baselines")
    evidence = [
        {
            "name": item.get("name"), "family": item.get("family"),
            "summary": item.get("summary") or {}, "analysis": item.get("analysis") or {},
            "behavior_evidence": item.get("behavior_evidence") or {},
        }
        for item in completed
    ]
    provenance = {
        "path": str(Path(path).resolve()),
        "run_id": record.get("run_id"),
        "settings": record.get("settings") or {},
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }
    return evidence, provenance
