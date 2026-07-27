from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import StudyConfig, load_study
from .forge import load_frozen_baselines, run_forge
from .io import write_json
from .manifest import ManifestStore
from .reliability import run_reliability
from .report import build_report


PACKAGE_ROOT = Path(__file__).resolve().parent
RUNS_ROOT = PACKAGE_ROOT / "runs"
DEFAULT_HISTORY_ROOT = PACKAGE_ROOT.parent / "backend" / "workspace" / "run_history"


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=PACKAGE_ROOT.parent, check=True,
            text=True, capture_output=True,
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _provenance() -> dict[str, Any]:
    return {
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_branch": _git_value("branch", "--show-current"),
        "git_dirty": bool(_git_value("status", "--porcelain")),
        "provider_model": os.getenv("MODEL", ""),
        "thinking_enabled": os.getenv("THINKING_ENABLED", ""),
    }


def _latest_baseline_history() -> Path:
    candidates = sorted(
        DEFAULT_HISTORY_ROOT.glob("forge-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            baselines, _ = load_frozen_baselines(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if len(baselines) >= 4:
            return path
    raise FileNotFoundError(
        "no completed four-baseline Forge history was found; pass --baseline-history"
    )


def _with_replicates(study: StudyConfig, replicates: int | None) -> StudyConfig:
    if replicates is None:
        return study
    if replicates < 1:
        raise ValueError("--replicates must be positive")
    return replace(study, replicates=replicates)


def plan(study: StudyConfig) -> dict[str, Any]:
    if study.kind == "reliability":
        calls = study.replicates * len(study.tracks) * len(study.arms)
        return {
            "study_id": study.study_id,
            "kind": study.kind,
            "replicates": study.replicates,
            "tracks": list(study.tracks),
            "arms": [arm.id for arm in study.arms],
            "scheduled_units": calls,
            "maximum_designer_calls_before_retries": calls,
            "lean_jobs": 0,
        }
    shared = study.replicates * len(study.tracks)
    branch_jobs = {
        "full": shared * 2,
        "no_critic": shared * 2,
        "no_baseline_context": shared * 3,
    }
    active = {arm.id for arm in study.arms}
    return {
        "study_id": study.study_id,
        "kind": study.kind,
        "replicates": study.replicates,
        "tracks": list(study.tracks),
        "arms": [arm.id for arm in study.arms],
        "shared_initial_lean_jobs": shared,
        "branch_lean_jobs": {key: value for key, value in branch_jobs.items() if key in active},
        "maximum_lean_jobs": shared + sum(value for key, value in branch_jobs.items() if key in active),
    }


def _execute(store: ManifestStore, study: StudyConfig, baseline_history: str | None) -> dict[str, Any]:
    store.set_status("running")
    try:
        if study.kind == "reliability":
            run_reliability(store, study)
        else:
            history = Path(baseline_history).resolve() if baseline_history else _latest_baseline_history()
            baselines, provenance = load_frozen_baselines(history)
            expected_settings = dict(study.run_settings)
            actual_settings = provenance.get("settings") or {}
            mismatches = {
                key: {"study": expected_settings.get(key), "history": actual_settings.get(key)}
                for key in expected_settings
                if expected_settings.get(key) != actual_settings.get(key)
            }
            if mismatches:
                raise ValueError(
                    "baseline history settings do not match the study: "
                    + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
                )
            store.set_frozen_input("public_baselines", {"provenance": provenance, "results": baselines})
            run_forge(store, study, baselines)
        manifest = store.read()
        incomplete = [
            unit_id for unit_id, unit in manifest["units"].items()
            if unit["status"] != "completed"
        ]
        report = build_report(store)
        if incomplete:
            store.set_status("failed", error=f"{len(incomplete)} experiment units did not complete")
        else:
            store.set_status("completed")
        return report
    except Exception as exc:
        store.set_status("failed", error=f"{type(exc).__name__}: {exc}")
        raise


def _require_live_confirmation(args: argparse.Namespace) -> None:
    if not args.confirm_live:
        raise SystemExit(
            "Live execution spends provider tokens and Worker time. Re-run with --confirm-live."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ablation")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan", help="validate and show a study without external calls")
    plan_parser.add_argument("--study", required=True)
    plan_parser.add_argument("--replicates", type=int)
    run_parser = sub.add_parser("run", help="create and execute a live experiment")
    run_parser.add_argument("--study", required=True)
    run_parser.add_argument("--replicates", type=int)
    run_parser.add_argument("--experiment-id")
    run_parser.add_argument("--baseline-history")
    run_parser.add_argument("--confirm-live", action="store_true")
    resume_parser = sub.add_parser("resume", help="resume incomplete experiment units")
    resume_parser.add_argument("--experiment-id", required=True)
    resume_parser.add_argument("--baseline-history")
    resume_parser.add_argument("--confirm-live", action="store_true")
    status_parser = sub.add_parser("status", help="show an experiment manifest summary")
    status_parser.add_argument("--experiment-id", required=True)
    report_parser = sub.add_parser("report", help="regenerate reports from persisted artifacts")
    report_parser.add_argument("--experiment-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        study = _with_replicates(load_study(args.study), args.replicates)
        print(json.dumps(plan(study), ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        _require_live_confirmation(args)
        study = _with_replicates(load_study(args.study), args.replicates)
        store = ManifestStore.create(
            RUNS_ROOT, study, provenance=_provenance(), experiment_id=args.experiment_id
        )
        write_json(store.experiment_dir / "config.snapshot.json", study.to_dict())
        report = _execute(store, study, args.baseline_history)
        print(json.dumps({"experiment_id": store.read()["experiment_id"], "report": report}, ensure_ascii=False, indent=2))
        return 0
    store = ManifestStore(RUNS_ROOT / args.experiment_id)
    if args.command == "status":
        manifest = store.read()
        counts: dict[str, int] = {}
        for unit in manifest["units"].values():
            counts[unit["status"]] = counts.get(unit["status"], 0) + 1
        print(json.dumps({"experiment_id": manifest["experiment_id"], "status": manifest["status"], "units": counts, "usage": manifest["usage"], "errors": manifest["errors"]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "report":
        print(json.dumps(build_report(store), ensure_ascii=False, indent=2))
        return 0
    _require_live_confirmation(args)
    manifest = store.read()
    if manifest["status"] == "completed":
        print(json.dumps({"experiment_id": manifest["experiment_id"], "status": "completed"}, indent=2))
        return 0
    store.recover_interrupted()
    study = StudyConfig.from_dict(manifest["config"])
    print(json.dumps(_execute(store, study, args.baseline_history), ensure_ascii=False, indent=2))
    return 0
