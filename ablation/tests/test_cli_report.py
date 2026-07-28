from __future__ import annotations

import json
from pathlib import Path

from ablation.cli import plan
from ablation.config import StudyConfig
from ablation.io import write_json
from ablation.manifest import ManifestStore
from ablation.report import build_report
from ablation import forge


def reliability_study() -> StudyConfig:
    return StudyConfig.from_dict({
        "schema_version": "1.0", "study_id": "test", "kind": "reliability",
        "description": "A complete test study.", "replicates": 1,
        "tracks": ["Traditional"], "max_parallel_tracks": 1,
        "arms": [{"id": "current", "label": "Current", "options": {}}],
        "run_settings": {}, "execution": {}, "reporting": {},
    })


def test_plan_is_read_only_cost_shape() -> None:
    result = plan(reliability_study())
    assert result["scheduled_units"] == 1
    assert result["lean_jobs"] == 0


def test_reliability_report_writes_all_formats(tmp_path: Path) -> None:
    study = reliability_study()
    store = ManifestStore.create(tmp_path, study, provenance={})
    store.register_units([{
        "id": "current/1/Traditional", "arm": "current", "replicate": 1,
        "track": "Traditional", "stage": "designer", "external_call": True,
    }])
    store.start_unit("current/1/Traditional")
    artifact = store.experiment_dir / "arms/current/1/Traditional.json"
    write_json(artifact, {
        "status": "passed", "first_schema_pass": True, "api_attempts": 1,
        "semantic_retry_count": 0, "strategy_spec_sha256": "abc",
        "elapsed_seconds": 1.5, "usage": {"total_tokens": 42},
    })
    store.complete_unit(
        "current/1/Traditional", artifact="arms/current/1/Traditional.json",
        usage={"total_tokens": 42},
    )
    report = build_report(store)
    assert report["groups"][0]["success_rate"] == 1.0
    assert (store.experiment_dir / "report.json").exists()
    assert (store.experiment_dir / "report.csv").exists()
    assert (store.experiment_dir / "report.md").exists()
    assert json.loads((store.experiment_dir / "manifest.json").read_text())["artifacts"]["report_json"] == "report.json"


def test_forge_tracks_share_one_worker_pool(monkeypatch, tmp_path: Path) -> None:
    study = StudyConfig.from_dict({
        "schema_version": "1.0", "study_id": "forge-test", "kind": "forge",
        "description": "Worker pool sharing test.", "replicates": 1,
        "tracks": ["Traditional", "ML", "Hybrid"], "max_parallel_tracks": 3,
        "arms": [{"id": "full", "label": "Full", "options": {}}],
        "run_settings": {
            "symbols": ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
            "start_date": "2020-01-02", "end_date": "2024-12-31",
            "initial_cash": 100000, "benchmark": "SPY",
            "transaction_cost_bps": 10, "slippage_bps": 5,
        },
        "execution": {}, "reporting": {},
    })
    store = ManifestStore.create(tmp_path, study, provenance={})
    shared_executor = object()
    monkeypatch.setattr(forge, "WorkerExecutor", lambda **_: shared_executor)
    observed: list[int] = []

    def capture(*args, **kwargs):
        factory = args[4]
        observed.append(id(factory()))

    monkeypatch.setattr(forge, "_ensure_shared", capture)
    monkeypatch.setattr(forge, "_ensure_branch", capture)
    forge.run_forge(store, study, [])
    assert len(observed) == 6
    assert len(set(observed)) == 1
