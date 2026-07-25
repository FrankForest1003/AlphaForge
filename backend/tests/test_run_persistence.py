from __future__ import annotations

import json
import threading

from app.services.baseline_service import BASELINES, ForgeService


def service(history_root):
    return ForgeService(
        worker=object(),
        designer=object(),
        critic=object(),
        allowed_symbols={"MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"},
        allowed_benchmarks={"SPY"},
        history_root=history_root,
    )


def completed_run(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "state": "completed",
        "stage": "Finished",
        "settings": {
            "symbols": ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
            "start_date": "2020-01-02",
            "end_date": "2024-12-31",
            "initial_cash": 100_000.0,
            "benchmark": "SPY",
            "transaction_cost_bps": 10.0,
            "slippage_bps": 5.0,
        },
        "baselines": [
            {
                "name": "Momentum Rank",
                "family": "Traditional",
                "state": "completed",
                "summary": {"sharpe_ratio": 1.0},
                "analysis": {
                    "equity_curve": [
                        {"date": "2020-01-02", "equity": 100_000.0}
                    ]
                },
            }
        ],
        "human": {
            "mode": "code",
            "guided": None,
            "state": "completed",
            "source_code": "class UserStrategy: pass",
            "summary": {"sharpe_ratio": 1.1},
            "analysis": {},
            "behavior_evidence": {},
            "error": None,
        },
        "candidates": [],
        "created_at": "2026-07-25T00:00:00+00:00",
        "updated_at": "2026-07-25T00:01:00+00:00",
        "error": None,
        "battle_analysis": {"education_summary": {"llm_state": "completed"}},
        "robustness": None,
        "battle_id": None,
        "round_number": None,
    }


def test_completed_runs_survive_service_restart_without_five_run_pruning(tmp_path):
    first = service(tmp_path)
    for index in range(7):
        run = completed_run(f"forge-persist{index}")
        first._runs[run["run_id"]] = run
        first._persist_history(run["run_id"])

    assert len(list(tmp_path.glob("forge-*.json"))) == 7

    restarted = service(tmp_path)
    restored = restarted.get("forge-persist0")

    assert restored is not None
    assert restored["state"] == "completed"
    assert restored["restored"] is True
    assert restored["human"]["source_code"] == "class UserStrategy: pass"
    assert restored["baselines"][0]["analysis"]["equity_curve"][0][
        "equity"
    ] == 100_000.0

    first._executor.shutdown(wait=False)
    restarted._executor.shutdown(wait=False)


def test_waiting_history_writer_snapshots_latest_education_state(tmp_path):
    forge = service(tmp_path)
    run = completed_run("forge-historyrace")
    run["battle_analysis"]["education_summary"]["llm_state"] = "pending"
    forge._runs[run["run_id"]] = run

    underlying_lock = threading.RLock()
    writer_waiting = threading.Event()

    class SignalingLock:
        def __enter__(self):
            writer_waiting.set()
            underlying_lock.acquire()

        def __exit__(self, exc_type, exc, traceback):
            underlying_lock.release()

    forge._history_lock = SignalingLock()
    underlying_lock.acquire()
    writer = threading.Thread(
        target=forge._persist_history,
        args=(run["run_id"],),
    )
    writer.start()
    assert writer_waiting.wait(timeout=1)
    with forge._lock:
        forge._runs[run["run_id"]]["battle_analysis"][
            "education_summary"
        ]["llm_state"] = "completed"
    underlying_lock.release()
    writer.join(timeout=2)
    assert not writer.is_alive()

    persisted = json.loads(
        (tmp_path / "forge-historyrace.json").read_text(encoding="utf-8")
    )
    assert persisted["battle_analysis"]["education_summary"][
        "llm_state"
    ] == "completed"
    forge._executor.shutdown(wait=False)


def test_sqlite_terminal_education_overrides_stale_v3_snapshot(tmp_path):
    first = service(tmp_path)
    run = completed_run("forge-staleeducation")
    run["battle_analysis"]["education_summary"]["llm_state"] = "pending"
    first._runs[run["run_id"]] = run
    first._persist_history(run["run_id"])

    class DurableRepository:
        def restore_run(self, run_id):
            assert run_id == "forge-staleeducation"
            durable = completed_run(run_id)
            durable["battle_analysis"]["education_summary"] = {
                "llm_state": "completed",
                "llm_review": {"strategy_explanation": {}},
                "llm_error": None,
            }
            durable["battle_id"] = "battle-test"
            durable["round_number"] = 1
            durable["user_id"] = "user-test"
            return durable

    restarted = ForgeService(
        worker=object(),
        designer=object(),
        critic=object(),
        allowed_symbols={"MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"},
        allowed_benchmarks={"SPY"},
        history_root=tmp_path,
        game_repository=DurableRepository(),
    )
    restored = restarted.get("forge-staleeducation")

    assert restored["battle_analysis"]["education_summary"][
        "llm_state"
    ] == "completed"
    first._executor.shutdown(wait=False)
    restarted._executor.shutdown(wait=False)
    restarted._coach_executor.shutdown(wait=False)


def test_battle_evidence_reuses_first_baselines_and_best_track_incumbent():
    baselines = [
        {
            "name": item["name"],
            "family": item["family"],
            "state": "completed",
            "summary": {"sharpe_ratio": 0.5},
            "analysis": {},
            "behavior_evidence": {},
        }
        for item in BASELINES
    ]

    def candidate(sharpe: float) -> dict:
        return {
            "track": "Traditional",
            "state": "accepted",
            "source_code": "class UserStrategy: pass",
            "strategy_spec": {"track": "Traditional"},
            "summary": {
                "sharpe_ratio": sharpe,
                "cagr": 0.2,
                "maximum_drawdown": 0.15,
            },
        }

    reused, incumbents = ForgeService._battle_evidence(
        [
            {
                "round_number": 1,
                "forge_run_id": "forge-r1",
                "result": {
                    "baselines": baselines,
                    "candidates": [candidate(0.9)],
                },
            },
            {
                "round_number": 2,
                "forge_run_id": "forge-r2",
                "result": {"candidates": [candidate(1.2)]},
            },
        ]
    )

    assert [item["name"] for item in reused] == [
        item["name"] for item in BASELINES
    ]
    assert incumbents["Traditional"]["summary"]["sharpe_ratio"] == 1.2
    assert incumbents["Traditional"]["_battle_round_number"] == 2
    assert incumbents["Traditional"]["_forge_run_id"] == "forge-r2"


def test_coach_rotates_a_stagnant_track_instead_of_repeating_small_tuning():
    candidate = {
        "track": "ML",
        "selection_origin": "prior_round_incumbent",
        "retained_from_round": 1,
        "iterations": [
            {
                "summary": {
                    "sharpe_ratio": 1.00,
                    "cagr": 0.20,
                    "maximum_drawdown": 0.20,
                }
            },
            {
                "summary": {
                    "sharpe_ratio": 1.01,
                    "cagr": 0.205,
                    "maximum_drawdown": 0.20,
                }
            },
        ],
    }
    diagnostic = ForgeService._coach_track_diagnostic(
        candidate,
        {
            "name": "Gradient Boosting",
            "summary": {"sharpe_ratio": 1.05, "cagr": 0.21},
        },
    )

    assert diagnostic["meaningful_trial_improvement"] is False
    assert diagnostic["recommended_next_move"] == "rotate_mechanism"
    assert diagnostic["recommended_change_scope"] == "model"
    assert diagnostic["recommended_parameter_change_budget"] == 2


def test_coach_rebuilds_a_flat_track_materially_behind_public_reference():
    candidate = {
        "track": "Hybrid",
        "selection_origin": "current_round",
        "iterations": [
            {
                "summary": {
                    "sharpe_ratio": 0.40,
                    "cagr": 0.08,
                    "maximum_drawdown": 0.35,
                }
            },
            {
                "summary": {
                    "sharpe_ratio": 0.41,
                    "cagr": 0.085,
                    "maximum_drawdown": 0.35,
                }
            },
        ],
    }
    diagnostic = ForgeService._coach_track_diagnostic(
        candidate,
        {
            "name": "Hybrid ML + Minimum Variance",
            "summary": {"sharpe_ratio": 1.10, "cagr": 0.24},
        },
    )

    assert diagnostic["materially_behind_public_reference"] is True
    assert diagnostic["recommended_next_move"] == "rebuild_track"
    assert diagnostic["recommended_parameter_change_budget"] == 4
