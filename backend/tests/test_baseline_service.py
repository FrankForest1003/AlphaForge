from __future__ import annotations

import time
import json
import threading
from datetime import date
from types import SimpleNamespace

import pytest

from agent import DeepSeekAcceptanceAgent, DeepSeekDesigner, DeepSeekRepairAgent
from agent.client import DeepSeekCallError, recover_known_payload
from app.schemas import GuidedHumanStrategy, HumanStrategyRequest, RunSettings
from app.services.baseline_service import (
    BASELINES,
    ForgeService,
    build_battle_analysis,
    build_guided_human_source,
    build_behavior_evidence,
    build_performance_analysis,
    build_revision_effectiveness,
    build_robustness_verdict,
    build_runtime_failure_evidence,
    classify_candidate_failure,
    compact_console_log,
    extract_critical_log_evidence,
    validate_acceptance_report,
)
from app.services.acceptance_policy import normalize_acceptance_payload


SYMBOLS = {"MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"}


def fake_design(track):
    if track == "Traditional":
        signal_family = "momentum"
        model_family = None
        label_horizon = None
    elif track == "ML":
        signal_family = None
        model_family = "gradient_boosting"
        label_horizon = 21
    else:
        signal_family = "momentum"
        model_family = "gradient_boosting"
        label_horizon = 21
    return {
        "strategy_name": f"Test {track}",
        "track": track,
        "thesis": "A deterministic test thesis.",
        "signals": ["momentum"] if track != "ML" else ["model prediction"],
        "features": [] if track == "Traditional" else ["ret_21"],
        "training_plan": None if track == "Traditional" else "Fit on prior rows.",
        "selection_rule": "Rank valid values and select the top two.",
        "rebalance_rule": "Rebalance monthly.",
        "reference_baselines": ["Momentum Rank", "Gradient Boosting"],
        "improvement_hypothesis": "Improve risk-adjusted return with a different bounded design.",
        "differentiation": [
            "Use a different feature mix.",
            "Use inverse-volatility weighting.",
        ],
        "expected_tradeoff": "Lower concentration may reduce both drawdown and upside capture.",
        "risk_controls": ["95% gross cap", "long-only weights"],
        "causal_chain": [
            "market rows",
            "signal",
            "ranking",
            "target weights",
            "af_rebalance_to_weights",
        ],
        "strategy_spec": {
            "signal_family": signal_family,
            "model_family": model_family,
            "rebalance_frequency": "monthly",
            "lookback_days": 126,
            "label_horizon_days": label_horizon,
            "top_k": 2,
            "weighting": "equal",
        },
    }


def fake_candidate_source(track):
    ml_lines = ""
    if track in {"ML", "Hybrid"}:
        ml_lines = """
        self.model.fit([[0.0], [1.0]], [0.0, 1.0])
        prediction = self.model.predict([[0.5]])[0]
        self.af_record_ml_training({
            "model_type": "Test",
            "training_rows": 2,
            "label_horizon_days": 1,
            "random_seed": 42,
            "feature_names": ["ret_21"],
        })
        self.af_record_ml_prediction(
            {"symbol": "MSFT", "predicted_alpha": prediction, "rank": 1, "selected": True}
        )
"""
    transparent = ""
    if track in {"Traditional", "Hybrid"}:
        transparent = (
            "momentum = 1.0\n"
            '        self.af_record_signal("momentum", {"symbol": "MSFT", "value": momentum})\n'
        )
    return f'''from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class UserStrategy(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize(self):
        symbols = self._parameter("symbols", "MSFT,AAPL,NVDA,GOOGL,AMZN")
        start_date = self._parameter("start_date", "2020-01-02")
        end_date = self._parameter("end_date", "2024-12-31")
        initial_cash = self._parameter("initial_cash", "100000")
        benchmark = self._parameter("benchmark", "SPY")
        transaction_cost_bps = self._parameter("transaction_cost_bps", "10")
        slippage_bps = self._parameter("slippage_bps", "5")
        self.af_configure_security(None)
        self.af_track_symbol(None)
{ml_lines.rstrip()}

    def rebalance(self):
        {transparent.rstrip()}
        self.set_holdings([])

    def on_data(self, data):
        pass
'''


def fake_agent_trace(label):
    return {
        "provider": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "request_parameters": {"model": "deepseek-v4-pro"},
        "dynamic_context": {"label": label},
        "raw_response": {"choices": [{"message": {"content": f"response-{label}"}}]},
        "response_content": f"response-{label}",
        "parsed_payload": {"label": label},
        "usage": {"total_tokens": 1},
        "error": None,
    }


class FakeWorker:
    def __init__(self) -> None:
        self.registry_submissions = []
        self.custom_submissions = []

    def submit(self, strategy_id, parameters):
        self.registry_submissions.append((strategy_id, dict(parameters)))
        return {"run_id": f"baseline-{len(self.registry_submissions)}", "state": "queued"}

    def submit_custom(self, source_code, parameters, timeout_seconds=None):
        self.custom_submissions.append((source_code, dict(parameters)))
        return {"run_id": f"candidate-{len(self.custom_submissions)}", "state": "queued"}

    def job(self, run_id):
        return {"run_id": run_id, "state": "completed", "result_path": "result.json"}

    def result(self, run_id):
        return {
            "status": "completed",
            "summary": {
                "cagr": 0.1,
                "sharpe_ratio": 1.0,
                "maximum_drawdown": 0.12,
                "end_equity": 110_000,
            },
            "evaluation": {"eligible_for_comparison": True, "rejection_reasons": []},
        }

    def log(self, run_id):
        return f"complete console log for {run_id}"

    def details(self, run_id):
        source_code = ""
        if run_id.startswith("candidate-"):
            index = int(run_id.split("-")[-1]) - 1
            if 0 <= index < len(self.custom_submissions):
                source_code = self.custom_submissions[index][0]
        event_time = "2024-01-02T16:00:00"
        rebalances = [
            {
                "time": event_time,
                "name": "decision_targets",
                "payload": {
                    "decision_id": f"{event_time}#1",
                    "targets": {"MSFT": 0.5},
                },
            },
            {
                "time": event_time,
                "name": "staged_rebalance_completed",
                "payload": {
                    "targets": {"MSFT": 0.5},
                    "actual_weights": {"MSFT": 0.5},
                },
            },
        ]
        signals = [
            {
                "time": event_time,
                "name": "decision_targets",
                "payload": {"targets": {"MSFT": 0.5}},
            }
        ]
        if "af_record_signal" in source_code:
            signals.append(
                {
                    "time": event_time,
                    "name": "momentum",
                    "payload": {"symbol": "MSFT", "value": 1.0},
                }
            )
        training_runs = []
        predictions = []
        if "af_record_ml_training" in source_code:
            training_runs.append(
                {
                    "time": event_time,
                    "model_type": "Test",
                    "training_rows": 2,
                }
            )
        if "af_record_ml_prediction" in source_code:
            predictions.append(
                {
                    "time": event_time,
                    "symbol": "MSFT",
                    "predicted_alpha": 0.1,
                    "selected": True,
                }
            )
        return {
            "orders": [
                {
                    "time": "2024-01-02T16:00:00",
                    "symbol": "MSFT",
                    "status": "FILLED",
                }
            ],
            "position_snapshots": [
                {
                    "gross_exposure": 0.5,
                    "positions": [{"symbol": "MSFT", "invested": True}],
                }
            ],
            "rebalances": rebalances,
            "signals": signals,
            "ml": {
                "training_runs": training_runs,
                "predictions": predictions,
            },
        }


class FakeDesigner:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, *, track, run_settings, baseline_results):
        self.calls.append((track, run_settings, baseline_results))
        return {
            "design": fake_design(track),
            "source_code": fake_candidate_source(track),
            "usage": {"total_tokens": 1},
            "trace": fake_agent_trace(f"designer-{track}"),
        }


class FakeRepairer:
    def __init__(self) -> None:
        self.calls = []

    def repair(
        self,
        *,
        track,
        run_settings,
        baseline_results,
        source_code,
        worker_result,
        lean_console_log,
        repair_attempt,
        repair_trigger,
        acceptance_report,
        validation_report=None,
        candidate_design=None,
    ):
        self.calls.append(
            {
                "name": f"repair-{track}-{repair_attempt}",
                "source_code": source_code,
                "worker_result": worker_result,
                "lean_console_log": lean_console_log,
                "repair_trigger": repair_trigger,
                "acceptance_report": acceptance_report,
                "validation_report": validation_report,
            }
        )
        return {
            "source_code": (
                source_code
                + f"\nREPAIR_REVISION_{repair_attempt} = {repair_attempt}\n"
                + f"# repaired {repair_attempt}\n"
            ),
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
            "trace": fake_agent_trace(f"repair-{track}-{repair_attempt}"),
        }


def acceptance_report(decision="accept", failed_id=None):
    checks = []
    for check_id in ("A1", "A2", "A3", "A4", "A5"):
        status = "fail" if check_id == failed_id else "pass"
        checks.append(
            {
                "id": check_id,
                "status": status,
                "evidence": [f"evidence for {check_id}"],
                "reason": f"reason for {check_id}",
            }
        )
    return {
        "decision": decision,
        "checks": checks,
        "repair_request": "repair the failed causal path" if decision == "revise" else None,
    }


class FakeAcceptanceAgent:
    def __init__(self, reports=None) -> None:
        self.reports = list(reports or [])
        self.calls = []

    def evaluate(self, **context):
        self.calls.append(context)
        report = self.reports.pop(0) if self.reports else acceptance_report()
        return {
            "report": report,
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            "trace": fake_agent_trace(f"acceptance-{len(self.calls)}"),
        }


class FailFirstCandidateWorker(FakeWorker):
    def result(self, run_id):
        if run_id == "candidate-2":
            return {
                "status": "failed",
                "summary": {},
                "errors": ["actual LEAN runtime error"],
            }
        return super().result(run_id)


class AlwaysFailCandidateWorker(FakeWorker):
    def result(self, run_id):
        if run_id.startswith("candidate-"):
            return {
                "status": "failed",
                "summary": {},
                "errors": [f"failure for {run_id}"],
            }
        return super().result(run_id)


def settings(**changes):
    values = {
        "symbols": ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
        "start_date": date(2020, 1, 2),
        "end_date": date(2024, 12, 31),
        "initial_cash": 100_000,
        "benchmark": "SPY",
        "transaction_cost_bps": 10,
        "slippage_bps": 5,
    }
    values.update(changes)
    return RunSettings(**values)


def human_code():
    return HumanStrategyRequest(
        mode="code",
        source_code=(
            "from AlgorithmImports import *\n\n"
            "class UserStrategy(QCAlgorithm):\n"
            "    def initialize(self):\n"
            "        self.symbol = self.add_equity('MSFT', Resolution.DAILY).symbol\n"
            "    def on_data(self, data):\n"
            "        if not self.portfolio.invested:\n"
            "            self.set_holdings(self.symbol, 0.8)\n"
        ),
    )


def human_guided(**changes):
    values = {
        "signal": "momentum",
        "lookback_days": 60,
        "rebalance": "monthly",
        "holdings": 2,
    }
    values.update(changes)
    return HumanStrategyRequest(
        mode="guided",
        guided=GuidedHumanStrategy(**values),
    )


def wait_for(service, run_id):
    for _ in range(100):
        run = service.get(run_id)
        if run["state"] in {"completed", "failed"}:
            return run
        time.sleep(0.01)
    raise AssertionError("forge run did not finish")


def test_run_settings_have_only_shared_market_and_execution_fields():
    value = settings()
    assert set(value.model_dump()) == {
        "symbols",
        "start_date",
        "end_date",
        "initial_cash",
        "benchmark",
        "transaction_cost_bps",
        "slippage_bps",
    }
    assert "top_k" not in value.worker_parameters()
    assert "random_seed" not in value.worker_parameters()
    with pytest.raises(ValueError, match="at least five"):
        settings(symbols=["MSFT"])


def test_guided_human_builds_complete_source_from_four_choices():
    request = human_guided(
        signal="mean_reversion",
        lookback_days=120,
        rebalance="weekly",
        holdings=3,
    )
    source = build_guided_human_source(request.guided)

    assert "class UserStrategy(AlphaForgeBaseAlgorithm)" in source
    assert "self.lookback_days = 120" in source
    assert "self.holdings = 3" in source
    assert "self.date_rules.week_start" in source
    assert "reverse=False" in source
    assert 'self._parameter("symbols"' in source
    assert "self.set_holdings(" in source
    assert "def initialize(self):" in source
    assert "def on_data(self, data):" in source
    assert "initialize_strategy" not in source


def test_three_designer_generation_requests_start_in_parallel():
    class ParallelDesigner(FakeDesigner):
        def __init__(self):
            super().__init__()
            self.barrier = threading.Barrier(3)

        def generate(self, *, track, run_settings, baseline_results):
            self.calls.append((track, run_settings, baseline_results))
            self.barrier.wait(timeout=2)
            return {
                "design": fake_design(track),
                "source_code": fake_candidate_source(track),
                "usage": {"total_tokens": 1},
            }

    designer = ParallelDesigner()
    service = ForgeService(
        worker=FakeWorker(),
        designer=designer,
        repairer=FakeRepairer(),
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )

    completed = wait_for(
        service,
        service.create(settings(), human_guided())["run_id"],
    )

    assert completed["state"] == "completed"
    assert {call[0] for call in designer.calls} == {"Traditional", "ML", "Hybrid"}
    assert all(item["state"] == "accepted" for item in completed["candidates"])


def test_forge_runs_four_baselines_human_and_three_designer_candidates():
    worker = FakeWorker()
    designer = FakeDesigner()
    repairer = FakeRepairer()
    acceptance = FakeAcceptanceAgent()
    service = ForgeService(
        worker=worker,
        designer=designer,
        repairer=repairer,
        acceptance_agent=acceptance,
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )

    created = service.create(settings(), human_code())
    completed = wait_for(service, created["run_id"])

    assert completed["state"] == "completed"
    assert [item[0] for item in worker.registry_submissions] == [
        item["strategy_id"] for item in BASELINES
    ]
    assert {item[0] for item in designer.calls} == {"Traditional", "ML", "Hybrid"}
    assert len(worker.custom_submissions) == 4
    assert completed["human"]["state"] == "completed"
    assert completed["human"]["source_code"] == human_code().source_code.strip()
    assert all(len(call[2]) == 4 for call in designer.calls)
    assert all(item["state"] == "accepted" for item in completed["candidates"])
    assert len(acceptance.calls) == 3
    assert all(len(item["acceptance_history"]) == 1 for item in completed["candidates"])
    assert all("contract" not in str(item).lower() for item in worker.registry_submissions)


def test_robustness_battery_runs_separately_after_forge_completion():
    worker = FakeWorker()
    service = ForgeService(
        worker=worker,
        designer=FakeDesigner(),
        repairer=FakeRepairer(),
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )
    created = service.create(settings(), human_guided())
    wait_for(service, created["run_id"])

    started = service.start_robustness(created["run_id"], "best_ai")
    assert started["state"] == "queued"
    for _ in range(100):
        robustness = service.get(created["run_id"])["robustness"]
        if robustness["state"] in {"completed", "failed"}:
            break
        time.sleep(0.01)

    assert robustness["state"] == "completed"
    assert robustness["verdict"]["policy_version"] == "deterministic-robustness-v1"
    assert len(robustness["scenarios"]) == 3
    assert all(item["state"] == "completed" for item in robustness["scenarios"])
    assert len(worker.custom_submissions) == 7


def test_forge_rejects_stock_outside_local_catalog():
    service = ForgeService(
        worker=FakeWorker(),
        designer=FakeDesigner(),
        repairer=FakeRepairer(),
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )
    with pytest.raises(ValueError, match="not available"):
        service.create(
            settings(symbols=["MSFT", "AAPL", "NVDA", "GOOGL", "TSLA"]),
            human_code(),
        )


def test_failed_candidate_is_repaired_with_complete_log_and_rerun():
    worker = FailFirstCandidateWorker()
    designer = FakeDesigner()
    repairer = FakeRepairer()
    service = ForgeService(
        worker=worker,
        designer=designer,
        repairer=repairer,
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )

    created = service.create(settings(), human_code())
    completed = wait_for(service, created["run_id"])

    repair_calls = repairer.calls
    assert completed["state"] == "completed"
    assert len(worker.custom_submissions) == 5
    assert len(repair_calls) == 1
    assert repair_calls[0]["name"] == "repair-Traditional-1"
    assert repair_calls[0]["worker_result"]["errors"] == ["actual LEAN runtime error"]
    assert repair_calls[0]["lean_console_log"] == "complete console log for candidate-2"
    assert repair_calls[0]["repair_trigger"] == "runtime_failure"
    assert repair_calls[0]["acceptance_report"] is None
    assert completed["candidates"][0]["state"] == "accepted"
    assert completed["candidates"][0]["repair_attempts"] == 1
    assert completed["candidates"][0]["usage"]["total_tokens"] == 18
    assert completed["candidates"][0]["source_code"].rstrip().endswith("# repaired 1")


def test_candidate_stops_after_three_failed_repairs():
    worker = AlwaysFailCandidateWorker()
    designer = FakeDesigner()
    repairer = FakeRepairer()
    service = ForgeService(
        worker=worker,
        designer=designer,
        repairer=repairer,
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )

    created = service.create(settings(), human_code())
    completed = wait_for(service, created["run_id"])

    repair_calls = repairer.calls
    assert completed["state"] == "completed"
    assert len(worker.custom_submissions) == 13
    assert len(repair_calls) == 9
    assert all(item["state"] == "failed" for item in completed["candidates"])
    assert all(item["repair_attempts"] == 3 for item in completed["candidates"])


def test_deepseek_prompt_uses_compact_contract_and_structured_design():
    class Completions:
        request = None
        content = json.dumps(
            {
                "design": fake_design("ML"),
                "source_code": fake_candidate_source("ML"),
            }
        )

        def create(self, **request):
            self.request = request
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=self.content)
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                ),
            )

    completions = Completions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    designer = DeepSeekDesigner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=True,
        lean_documentation="FULL ORIGINAL DOCUMENT TEXT",
        client=client,
    )
    result = designer.generate(
        track="ML",
        run_settings=settings().model_dump(mode="json"),
        baseline_results=[{"name": "Baseline", "family": "ML", "summary": {}}] * 4,
    )

    request = completions.request
    prompt = request["messages"][1]["content"]
    assert prompt.index("ALPHAFORGE AGENT CAPABILITY CONTRACT") < prompt.index(
        "ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE"
    )
    assert prompt.index("ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE") < prompt.index(
        "DESIGNER REQUEST"
    )
    assert "FULL ORIGINAL DOCUMENT TEXT" not in prompt
    assert "OFFICIAL QUANTCONNECT WRITING ALGORITHMS DOCUMENTATION" not in prompt
    assert len(prompt) < 20_000
    assert '"design"' in prompt
    assert '"source_code"' in prompt
    assert "af_rebalance_daily_weights" in prompt
    assert "Standard set_holdings, liquidate" in prompt
    assert "exactly one dict positional argument" in prompt
    assert "LEAN Python ScheduleManager has no `.do(...)` builder" in prompt
    assert '"label_horizon_days"' in prompt
    assert '"reference_baselines"' in prompt
    assert '"improvement_hypothesis"' in prompt
    assert "differ from the closest baseline in exactly two" in prompt
    assert '"selected": bool(symbol in selected_symbols)' in prompt
    assert "max_position_weight" not in prompt
    assert "contract_hash" not in prompt
    assert "unassisted" not in prompt.lower()
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert result["usage"]["total_tokens"] == 120
    assert result["design"]["track"] == "ML"
    assert "messages" not in result["trace"]["request_parameters"]
    assert result["trace"]["dynamic_context"]["designer_track"] == "ML"
    assert result["trace"]["dynamic_context"]["run_settings"]["symbols"] == [
        "MSFT",
        "AAPL",
        "NVDA",
        "GOOGL",
        "AMZN",
    ]
    assert "FULL ORIGINAL DOCUMENT TEXT" not in json.dumps(result["trace"])
    assert result["trace"]["response_content"] == Completions.content
    assert result["trace"]["raw_response"]["choices"][0]["message"]["content"] == Completions.content
    assert "test-key" not in json.dumps(result["trace"])

    repairer = DeepSeekRepairAgent(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=True,
        lean_documentation="FULL ORIGINAL DOCUMENT TEXT",
        client=client,
    )
    completions.content = json.dumps(
        {
            "change_summary": ["Corrected the observed runtime API call."],
            "first_interrupted_stage": "runtime API invocation",
            "source_code": "REPAIRED COMPLETE SOURCE",
        }
    )
    repairer.repair(
        track="ML",
        run_settings=settings().model_dump(mode="json"),
        baseline_results=[],
        source_code="BROKEN COMPLETE SOURCE",
        worker_result={"status": "failed", "errors": ["TRACEBACK"]},
        lean_console_log="FULL LEAN CONSOLE LOG",
        repair_attempt=1,
        repair_trigger="acceptance_revision",
        acceptance_report=acceptance_report("revise", "A2"),
    )
    repair_prompt = completions.request["messages"][1]["content"]
    assert repair_prompt.index("ALPHAFORGE AGENT CAPABILITY CONTRACT") < repair_prompt.index(
        "ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE"
    )
    assert repair_prompt.index("ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE") < repair_prompt.index(
        "REPAIR REQUEST"
    )
    assert "FULL ORIGINAL DOCUMENT TEXT" not in repair_prompt
    assert len(repair_prompt) < 30_000
    assert "BROKEN COMPLETE SOURCE" in repair_prompt
    assert "FULL LEAN CONSOLE LOG" in repair_prompt
    assert '"lean_console_log_excerpt"' in repair_prompt
    assert "af_rebalance_daily_weights" in repair_prompt
    assert "Standard set_holdings, liquidate" in repair_prompt
    assert "max_position_weight" not in repair_prompt
    assert '"repair_attempt": 1' in repair_prompt
    assert '"repair_trigger": "acceptance_revision"' in repair_prompt
    assert '"acceptance_report"' in repair_prompt

    completions.content = json.dumps(acceptance_report())
    acceptance = DeepSeekAcceptanceAgent(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=True,
        client=client,
    )
    acceptance.evaluate(
        track="ML",
        run_settings=settings().model_dump(mode="json"),
        critical_log_evidence="STATISTICS:: Total Orders 1",
        source_code="COMPLETE CANDIDATE SOURCE",
        worker_result={"status": "completed"},
        lean_console_log="COMPLETE LEAN LOG",
        behavior_evidence={
            "filled_order_count": 1,
            "invested_snapshot_count": 1,
            "max_gross_exposure": 0.5,
        },
        acceptance_attempt=1,
    )
    acceptance_prompt = completions.request["messages"][1]["content"]
    assert acceptance_prompt.index("ALPHAFORGE ACCEPTANCE RULES") < acceptance_prompt.index(
        "ACCEPTANCE REQUEST"
    )
    assert "COMPLETE CANDIDATE SOURCE" in acceptance_prompt
    assert "COMPLETE LEAN LOG" in acceptance_prompt
    assert '"lean_console_log_excerpt"' in acceptance_prompt
    assert "STATISTICS:: Total Orders 1" in acceptance_prompt
    assert acceptance_prompt.index('"behavior_gate"') < acceptance_prompt.index(
        '"source_code"'
    )
    assert "FULL ORIGINAL DOCUMENT TEXT" not in acceptance_prompt
    assert "QUANTCONNECT PYTHON TEMPLATE" not in acceptance_prompt
    assert "baseline_results" not in acceptance_prompt


def test_deepseek_invalid_json_keeps_raw_response_for_replay():
    class Completions:
        def create(self, **request):
            return SimpleNamespace(
                id="response-id",
                choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))],
                usage=SimpleNamespace(
                    prompt_tokens=7,
                    completion_tokens=2,
                    total_tokens=9,
                ),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    designer = DeepSeekDesigner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=False,
        lean_documentation="FULL DOCUMENT",
        client=client,
    )

    with pytest.raises(DeepSeekCallError) as raised:
        designer.generate(
            track="ML",
            run_settings=settings().model_dump(mode="json"),
            baseline_results=[],
        )

    trace = raised.value.trace
    assert trace["response_content"] == "not json"
    assert trace["raw_response"]["id"] == "response-id"
    assert trace["usage"]["total_tokens"] == 18
    assert len(trace["attempts"]) == 2
    assert trace["attempts"][1]["thinking_enabled"] is False
    assert trace["error"]["type"] == "invalid_json"
    assert "test-key" not in json.dumps(trace)


def test_designer_retries_once_after_semantic_schema_failure():
    invalid_design = fake_design("ML")
    invalid_design["signals"] = []
    responses = [
        json.dumps(
            {
                "design": invalid_design,
                "source_code": fake_candidate_source("ML"),
            }
        ),
        json.dumps(
            {
                "design": fake_design("ML"),
                "source_code": fake_candidate_source("ML"),
            }
        ),
    ]

    class Completions:
        requests = []

        def create(self, **request):
            self.requests.append(request)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=responses[len(self.requests) - 1])
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            )

    completions = Completions()
    designer = DeepSeekDesigner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=False,
        lean_documentation="FULL DOCUMENT",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    generated = designer.generate(
        track="ML",
        run_settings=settings().model_dump(mode="json"),
        baseline_results=[],
    )

    assert len(completions.requests) == 2
    assert "design.signals must be a list of non-empty strings" in (
        completions.requests[1]["messages"][-1]["content"]
    )
    assert generated["usage"]["total_tokens"] == 30
    assert generated["trace"]["semantic_retry_count"] == 1
    assert [item["status"] for item in generated["trace"]["semantic_validation_attempts"]] == [
        "schema_failed",
        "passed",
    ]


def test_json_and_semantic_failures_share_two_model_call_budget():
    invalid_design = fake_design("ML")
    invalid_design["signals"] = []
    responses = [
        "not json",
        json.dumps(
            {
                "design": invalid_design,
                "source_code": fake_candidate_source("ML"),
            }
        ),
    ]

    class Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **request):
            content = responses[self.calls]
            self.calls += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            )

    completions = Completions()
    designer = DeepSeekDesigner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=True,
        lean_documentation="FULL DOCUMENT",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    with pytest.raises(DeepSeekCallError):
        designer.generate(
            track="ML",
            run_settings=settings().model_dump(mode="json"),
            baseline_results=[],
        )

    assert completions.calls == 2


def test_designer_normalizes_lossless_scalar_string_lists_without_retry():
    design = fake_design("ML")
    design["signals"] = "RandomForest prediction"
    design["reference_baselines"] = "Gradient Boosting"

    normalized = DeepSeekDesigner._validated_design(
        {"design": design},
        "ML",
    )

    assert normalized["signals"] == ["RandomForest prediction"]
    assert normalized["reference_baselines"] == ["Gradient Boosting"]
    assert normalized["differentiation"] == [
        "Use a different feature mix.",
        "Use inverse-volatility weighting.",
    ]


def test_repairer_retries_once_after_semantic_schema_failure():
    responses = [
        json.dumps(
            {
                "change_summary": [],
                "first_interrupted_stage": "",
                "source_code": "BROKEN COMPLETE SOURCE",
            }
        ),
        json.dumps(
            {
                "change_summary": ["Corrected the failing schedule call."],
                "first_interrupted_stage": "scheduled rebalance",
                "source_code": "REPAIRED COMPLETE SOURCE",
            }
        ),
    ]

    class Completions:
        def __init__(self):
            self.requests = []

        def create(self, **request):
            self.requests.append(request)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=responses[len(self.requests) - 1]
                        )
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            )

    completions = Completions()
    repairer = DeepSeekRepairAgent(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=False,
        lean_documentation="FULL DOCUMENT",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    repaired = repairer.repair(
        track="ML",
        run_settings=settings().model_dump(mode="json"),
        baseline_results=[],
        source_code="BROKEN COMPLETE SOURCE",
        worker_result={"status": "failed"},
        lean_console_log="runtime failure",
        repair_attempt=1,
        repair_trigger="runtime_failure",
    )

    assert len(completions.requests) == 2
    assert "change_summary" in completions.requests[1]["messages"][-1]["content"]
    assert repaired["source_code"] == "REPAIRED COMPLETE SOURCE"
    assert repaired["usage"]["total_tokens"] == 30
    assert repaired["trace"]["semantic_retry_count"] == 1


def test_designer_recovers_complete_source_when_only_json_closure_is_missing():
    design = fake_design("ML")
    source = fake_candidate_source("ML")
    malformed = (
        '{"design":'
        + json.dumps(design)
        + ',"source_code":'
        + json.dumps(source)[:-1]
    )

    class Completions:
        calls = 0

        def create(self, **request):
            self.calls += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=malformed))],
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                ),
            )

    completions = Completions()
    designer = DeepSeekDesigner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=False,
        lean_documentation="FULL DOCUMENT",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    generated = designer.generate(
        track="ML",
        run_settings=settings().model_dump(mode="json"),
        baseline_results=[],
    )

    assert generated["source_code"] == source.strip()
    assert generated["design"]["track"] == "ML"
    assert completions.calls == 1
    assert generated["trace"]["attempts"][0]["parse_mode"] == "recovered_known_payload"
    assert recover_known_payload(malformed)["source_code"] == source


def test_forge_trace_persists_every_agent_call_and_worker_source(tmp_path):
    worker = AlwaysFailCandidateWorker()
    service = ForgeService(
        worker=worker,
        designer=FakeDesigner(),
        repairer=FakeRepairer(),
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
        trace_root=tmp_path,
    )

    completed = wait_for(service, service.create(settings(), human_code())["run_id"])
    trace = service.get_trace(completed["run_id"])

    assert trace["state"] == "completed"
    assert trace["schema_version"] == "1.1"
    assert "human_source" in trace["context_manifest"]["ai_forge_excludes"]
    assert len(trace["agent_calls"]) == 12
    assert len(trace["validation_attempts"]) == 12
    assert len(trace["worker_attempts"]) == 12
    traditional = [
        item for item in trace["worker_attempts"] if item["track"] == "Traditional"
    ]
    assert [item["attempt"] for item in traditional] == [0, 1, 2, 3]
    assert traditional[0]["source_code"].endswith("pass\n")
    assert traditional[-1]["source_code"].endswith("# repaired 3\n")
    assert all(item["result"]["status"] == "failed" for item in traditional)
    assert all("complete console log" in item["console_log"] for item in traditional)
    assert all(item["outcome"] == "runtime_failure" for item in traditional)
    assert all(item["call"]["request_parameters"] for item in trace["agent_calls"])
    assert all(item["call"]["dynamic_context"] for item in trace["agent_calls"])

    persisted_path = tmp_path / f"{completed['run_id']}.json"
    assert persisted_path.is_file()
    persisted_text = persisted_path.read_text(encoding="utf-8")
    assert "API_KEY" not in persisted_text
    assert "test-key" not in persisted_text
    assert "class UserStrategy:\\n    pass" not in persisted_text

    reloaded = ForgeService(
        worker=FakeWorker(),
        designer=FakeDesigner(),
        repairer=FakeRepairer(),
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
        trace_root=tmp_path,
    ).get_trace(completed["run_id"])
    assert reloaded == trace


def test_behavior_evidence_uses_filled_orders_and_invested_snapshots():
    evidence = build_behavior_evidence(FakeWorker().details("candidate-1"))
    assert evidence["evidence_schema_version"] == "2.0"
    assert evidence["order_count"] == 1
    assert evidence["filled_order_count"] == 1
    assert evidence["invested_snapshot_count"] == 1
    assert evidence["max_gross_exposure"] == 0.5
    assert evidence["traded_symbols"] == ["MSFT"]
    assert evidence["target_intent_event_count"] == 1
    assert evidence["transparent_signal_event_count"] == 0
    assert evidence["staged_rebalance_started_count"] == 1
    assert evidence["staged_rebalance_completed_count"] == 1


def test_public_analysis_builds_equity_drawdown_cost_and_turnover():
    details = {
        "equity_curve": [
            {"time": "2024-01-02T16:00:00", "portfolio_value": 100_000, "cash": 5_000},
            {"time": "2024-01-03T16:00:00", "portfolio_value": 110_000, "cash": 4_000},
            {"time": "2024-01-04T16:00:00", "portfolio_value": 99_000, "cash": 3_000},
        ],
        "benchmark_curve": [
            {"time": "2024-01-02T16:00:00", "normalized_value": 1.0},
            {"time": "2024-01-04T16:00:00", "normalized_value": 1.05},
        ],
        "order_events": [
            {"fill_quantity": 10, "fill_price": 100, "fee": 2.5},
        ],
    }
    analysis = build_performance_analysis(
        details,
        {"end_equity": 99_000, "maximum_drawdown": 0.10},
        initial_cash=100_000,
    )

    assert analysis["equity_curve"][-1]["drawdown"] == pytest.approx(-0.10)
    assert analysis["statistics"]["total_return"] == pytest.approx(-0.01)
    assert analysis["statistics"]["total_fees"] == pytest.approx(2.5)
    assert analysis["statistics"]["benchmark_total_return"] == pytest.approx(0.05)


def test_robustness_verdict_scores_deterministic_stress_scenarios():
    scenarios = [
        {
            "id": scenario_id,
            "state": "completed",
            "summary": {
                "cagr": cagr,
                "sharpe_ratio": 0.9,
                "maximum_drawdown": 0.24,
            },
            "behavior_evidence": {
                "filled_order_count": 12,
                "max_gross_exposure": 0.9,
            },
        }
        for scenario_id, cagr in (
            ("recent_regime", 0.12),
            ("delayed_start", 0.11),
            ("friction_2x", 0.16),
        )
    ]

    verdict = build_robustness_verdict(
        {
            "cagr": 0.20,
            "sharpe_ratio": 1.0,
            "maximum_drawdown": 0.20,
        },
        scenarios,
    )

    assert verdict["grade"] == "robust"
    assert verdict["score"] == 100
    assert all(len(item["checks"]) == 4 for item in scenarios)


def test_predictions_without_training_has_specific_causal_classification():
    classification = classify_candidate_failure(
        result={"status": "completed"},
        console_log="",
        behavior_evidence={
            "filled_order_count": 20,
            "ml_training_run_count": 0,
            "ml_prediction_count": 40,
        },
    )

    assert classification["code"] == "PREDICTIONS_WITHOUT_TRAINING"
    assert "row cardinality" in classification["summary"]


def test_runtime_failure_evidence_relates_order_event_and_portfolio():
    details = {
        "orders": [
            {
                "order_id": 96,
                "symbol": "AMZN",
                "quantity": 1099,
                "status": "INVALID",
                "time": "2024-01-03T16:00:00",
            }
        ],
        "order_events": [
            {
                "order_id": 96,
                "symbol": "AMZN",
                "status": "INVALID",
                "time": "2024-01-03T16:00:00",
                "message": "Insufficient buying power",
            }
        ],
        "position_snapshots": [
            {"time": "2024-01-03T15:59:00", "cash": 1_000, "portfolio_value": 100_000}
        ],
    }
    evidence = build_runtime_failure_evidence(
        details,
        "ERROR:: Order Error: ids: [96] Insufficient buying power",
    )

    assert evidence["failed_order_count"] == 1
    assert evidence["failed_orders"][0]["order"]["symbol"] == "AMZN"
    assert evidence["failed_orders"][0]["portfolio_before_failure"]["cash"] == 1_000


def test_runtime_failure_evidence_keeps_every_failed_order():
    details = {
        "orders": [
            {
                "order_id": order_id,
                "symbol": "MSFT",
                "quantity": 1,
                "status": "INVALID",
                "time": f"2024-01-03T16:{order_id:02d}:00",
            }
            for order_id in range(20)
        ],
        "order_events": [
            {
                "order_id": order_id,
                "symbol": "MSFT",
                "status": "INVALID",
                "time": f"2024-01-03T16:{order_id:02d}:00",
                "message": "Rejected",
            }
            for order_id in range(20)
        ],
        "position_snapshots": [],
    }
    evidence = build_runtime_failure_evidence(details, "ERROR:: rejected")

    assert evidence["failed_order_count"] == 20
    assert len(evidence["failed_orders"]) == 20
    assert evidence["evidence_truncated"] is False


def test_critical_log_evidence_is_verbatim_and_focused():
    console_log = (
        "noise before\n"
        "Debug: Algorithm finished warming up.\n"
        "STATISTICS:: Total Orders 0\n"
        "STATISTICS:: End Equity 100000\n"
        "DATA USAGE:: Failed data requests 0\n"
        "noise after\n"
    )
    assert extract_critical_log_evidence(console_log) == (
        "Debug: Algorithm finished warming up.\n"
        "STATISTICS:: Total Orders 0\n"
        "STATISTICS:: End Equity 100000\n"
        "DATA USAGE:: Failed data requests 0"
    )


def test_agent_log_context_is_bounded_but_full_worker_log_is_not_mutated():
    console_log = (
        "initialization line\n"
        + ("Debug: repeated per-bar diagnostic\n" * 20_000)
        + "ERROR:: PythonException: concrete failure\n"
        + "  in main.py: line 123\n"
        + "STATISTICS:: Total Orders 0\n"
    )
    compact = compact_console_log(console_log, max_chars=4_000)

    assert len(compact) <= 4_000
    assert "original_chars=" in compact
    assert "concrete failure" in compact
    assert "main.py: line 123" in compact
    assert "STATISTICS:: Total Orders 0" in compact
    assert len(console_log) > len(compact)


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        (
            "No method matches given arguments for on: "
            "(FuncDateRule, FuncTimeRule)",
            "LEAN_SCHEDULE_SIGNATURE",
        ),
        (
            "AlphaForgeBaseAlgorithm.af_record_ml_training() takes 2 "
            "positional arguments but 6 were given",
            "ALPHAFORGE_EVIDENCE_SIGNATURE",
        ),
        (
            "AlphaForgeBaseAlgorithm.af_record_ml_prediction() got an "
            "unexpected keyword argument 'symbol'",
            "ALPHAFORGE_EVIDENCE_SIGNATURE",
        ),
    ],
)
def test_known_runtime_contract_failures_have_stable_classifications(
    message,
    expected_code,
):
    classified = classify_candidate_failure(
        result={"status": "failed", "errors": [message]},
        console_log=message,
    )
    assert classified["code"] == expected_code


def test_revision_effectiveness_distinguishes_evidence_only_from_no_op():
    previous = {
        "summary": {
            "cagr": 0.1,
            "sharpe_ratio": 1.0,
            "maximum_drawdown": 0.2,
            "end_equity": 110_000,
        },
        "behavior_evidence": {
            "filled_order_count": 20,
            "invested_snapshot_count": 100,
            "max_gross_exposure": 0.9,
            "rebalance_count": 12,
            "nonzero_target_event_count": 12,
            "signal_event_count": 12,
            "ml_training_run_count": 4,
            "ml_prediction_count": 60,
        },
        "preflight": {"semantic_sha256": "before"},
        "report": acceptance_report("revise", "A2"),
    }
    report = acceptance_report()
    evidence_only = build_revision_effectiveness(
        previous=previous,
        summary=previous["summary"],
        behavior_evidence=previous["behavior_evidence"],
        preflight={"semantic_sha256": "after"},
        report=report,
    )
    no_op = build_revision_effectiveness(
        previous=previous,
        summary=previous["summary"],
        behavior_evidence=previous["behavior_evidence"],
        preflight={"semantic_sha256": "before"},
        report=report,
    )

    assert evidence_only["effective"] is True
    assert evidence_only["kind"] == "evidence_only"
    assert evidence_only["resolved_checks"] == ["A2"]
    assert no_op["effective"] is False
    assert no_op["kind"] == "ineffective"


def test_independent_agent_revision_triggers_repair_and_rerun():
    worker = FakeWorker()
    repairer = FakeRepairer()
    acceptance = FakeAcceptanceAgent(
        [acceptance_report("revise", "A2"), acceptance_report()]
    )
    service = ForgeService(
        worker=worker,
        designer=FakeDesigner(),
        repairer=repairer,
        acceptance_agent=acceptance,
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )

    completed = wait_for(service, service.create(settings(), human_code())["run_id"])

    first = completed["candidates"][0]
    assert first["state"] == "accepted"
    assert first["repair_attempts"] == 1
    assert len(first["acceptance_history"]) == 2
    assert first["acceptance"]["decision"] == "accept"
    assert len(repairer.calls) == 1
    assert len(worker.custom_submissions) == 5


def test_history_keeps_latest_five_pk_rounds(tmp_path):
    history_root = tmp_path / "history"
    service = ForgeService(
        worker=FakeWorker(),
        designer=FakeDesigner(),
        repairer=FakeRepairer(),
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
        trace_root=tmp_path / "traces",
        history_root=history_root,
    )
    created_ids = []
    for _ in range(6):
        created = service.create(settings(), human_code())
        completed = wait_for(service, created["run_id"])
        created_ids.append(completed["run_id"])

    history = service.list_history()
    assert len(history) == 5
    assert created_ids[0] not in {item["run_id"] for item in history}
    assert created_ids[-1] in {item["run_id"] for item in history}
    latest = service.get_history(created_ids[-1])
    assert latest["winner"]["side"] in {"human", "ai", "draw"}
    assert latest["battle_analysis"]["judge"]["method"] == "deterministic_weighted_score_v1"
    assert "source_code" not in latest["human"]
    assert len(list(history_root.glob("forge-*.json"))) == 5


def test_a1_cannot_accept_zero_activity_even_when_agent_says_accept():
    class ZeroActivityWorker(FakeWorker):
        def details(self, run_id):
            return {"orders": [], "position_snapshots": [], "rebalances": []}

    repairer = FakeRepairer()
    service = ForgeService(
        worker=ZeroActivityWorker(),
        designer=FakeDesigner(),
        repairer=repairer,
        acceptance_agent=FakeAcceptanceAgent(),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )

    completed = wait_for(service, service.create(settings(), human_code())["run_id"])

    assert all(item["state"] == "failed" for item in completed["candidates"])
    assert all("A1 contradicts behavior evidence" in item["error"] for item in completed["candidates"])
    assert len(repairer.calls) == 0


def test_acceptance_revisions_share_three_repair_attempt_limit():
    reports = [acceptance_report("revise", "A2") for _ in range(12)]
    worker = FakeWorker()
    repairer = FakeRepairer()
    service = ForgeService(
        worker=worker,
        designer=FakeDesigner(),
        repairer=repairer,
        acceptance_agent=FakeAcceptanceAgent(reports),
        allowed_symbols=SYMBOLS,
        allowed_benchmarks={"SPY"},
    )

    completed = wait_for(service, service.create(settings(), human_code())["run_id"])

    assert len(worker.custom_submissions) == 13
    assert len(repairer.calls) == 9
    assert all(item["state"] == "rejected" for item in completed["candidates"])
    assert all(item["repair_attempts"] == 3 for item in completed["candidates"])
    assert all(len(item["acceptance_history"]) == 4 for item in completed["candidates"])


def test_nested_provider_output_is_unwrapped():
    report = acceptance_report("revise", "A2")
    assert normalize_acceptance_payload({"output": report}) == report


def test_backend_preserves_independent_hybrid_semantic_judgment():
    evidence = {
        "filled_order_count": 100,
        "invested_snapshot_count": 200,
        "max_gross_exposure": 0.95,
        "traded_symbols": ["MSFT"],
        "transparent_signal_event_count": 10,
        "signal_to_target_link_count": 10,
        "target_intent_event_count": 10,
        "nonzero_target_event_count": 10,
        "ml_training_run_count": 0,
        "ml_prediction_count": 0,
        "hybrid_decision_link_count": 0,
        "training_before_prediction_count": 0,
    }
    agent_report = acceptance_report("revise", "A3")
    report = validate_acceptance_report(
        agent_report,
        evidence,
        {"symbols": ["MSFT"], "benchmark": "SPY"},
    )
    by_id = {item["id"]: item for item in report["checks"]}
    assert report["decision"] == "revise"
    assert by_id["A1"]["status"] == "pass"
    assert by_id["A2"]["status"] == "pass"
    assert by_id["A3"]["status"] == "fail"
