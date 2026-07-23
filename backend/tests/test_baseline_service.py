from __future__ import annotations

import time
import json
import threading
from datetime import date
from types import SimpleNamespace

import pytest

from agent import DeepSeekAcceptanceAgent, DeepSeekDesigner, DeepSeekRepairAgent
from app.schemas import GuidedHumanStrategy, HumanStrategyRequest, RunSettings
from app.services.baseline_service import (
    BASELINES,
    ForgeService,
    build_guided_human_source,
    build_behavior_evidence,
    extract_critical_log_evidence,
    validate_acceptance_report,
)


SYMBOLS = {"MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"}


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
            "rebalances": [{"time": "2024-01-02T16:00:00"}],
        }


class FakeDesigner:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, *, track, run_settings, baseline_results):
        self.calls.append((track, run_settings, baseline_results))
        return {
            "source_code": f"class UserStrategy:  # {track}\n    pass\n",
            "usage": {"total_tokens": 1},
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
    ):
        self.calls.append(
            {
                "name": f"repair-{track}-{repair_attempt}",
                "source_code": source_code,
                "worker_result": worker_result,
                "lean_console_log": lean_console_log,
                "repair_trigger": repair_trigger,
                "acceptance_report": acceptance_report,
            }
        )
        return {
            "source_code": source_code + f"# repaired {repair_attempt}\n",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
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
        source_code="class UserStrategy:\n    pass\n",
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
    value = settings(symbols=["MSFT"])
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
    assert "af_rebalance_to_weights" in source


def test_three_designer_generation_requests_start_in_parallel():
    class ParallelDesigner(FakeDesigner):
        def __init__(self):
            super().__init__()
            self.barrier = threading.Barrier(3)

        def generate(self, *, track, run_settings, baseline_results):
            self.calls.append((track, run_settings, baseline_results))
            self.barrier.wait(timeout=2)
            return {
                "source_code": f"class UserStrategy:  # {track}\n    pass\n",
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
    assert completed["human"]["source_code"] == "class UserStrategy:\n    pass"
    assert all(len(call[2]) == 4 for call in designer.calls)
    assert all(item["state"] == "accepted" for item in completed["candidates"])
    assert len(acceptance.calls) == 3
    assert all(len(item["acceptance_history"]) == 1 for item in completed["candidates"])
    assert all("contract" not in str(item).lower() for item in worker.registry_submissions)


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
        service.create(settings(symbols=["TSLA"]), human_code())


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


def test_deepseek_prompt_keeps_static_text_first_and_requests_only_source_code():
    class Completions:
        request = None
        content = json.dumps({"source_code": "class UserStrategy:\n    pass\n"})

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
    assert prompt.index("ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE") < prompt.index(
        "OFFICIAL QUANTCONNECT WRITING ALGORITHMS DOCUMENTATION"
    )
    assert prompt.index("OFFICIAL QUANTCONNECT WRITING ALGORITHMS DOCUMENTATION") < prompt.index(
        "DESIGNER REQUEST"
    )
    assert "FULL ORIGINAL DOCUMENT TEXT" in prompt
    assert '"source_code"' in prompt
    assert "af_rebalance_to_weights" in prompt
    assert "max_position_weight" not in prompt
    assert "contract_hash" not in prompt
    assert "unassisted" not in prompt.lower()
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert result["usage"]["total_tokens"] == 120

    repairer = DeepSeekRepairAgent(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        thinking_enabled=True,
        lean_documentation="FULL ORIGINAL DOCUMENT TEXT",
        client=client,
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
    assert repair_prompt.index("ALPHAFORGE QUANTCONNECT PYTHON TEMPLATE") < repair_prompt.index(
        "OFFICIAL QUANTCONNECT WRITING ALGORITHMS DOCUMENTATION"
    )
    assert repair_prompt.index("OFFICIAL QUANTCONNECT WRITING ALGORITHMS DOCUMENTATION") < repair_prompt.index(
        "REPAIR REQUEST"
    )
    assert "FULL ORIGINAL DOCUMENT TEXT" in repair_prompt
    assert "BROKEN COMPLETE SOURCE" in repair_prompt
    assert "FULL LEAN CONSOLE LOG" in repair_prompt
    assert "af_rebalance_to_weights" in repair_prompt
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
    assert "STATISTICS:: Total Orders 1" in acceptance_prompt
    assert acceptance_prompt.index('"behavior_gate"') < acceptance_prompt.index(
        '"source_code"'
    )
    assert "FULL ORIGINAL DOCUMENT TEXT" not in acceptance_prompt
    assert "QUANTCONNECT PYTHON TEMPLATE" not in acceptance_prompt
    assert "baseline_results" not in acceptance_prompt


def test_behavior_evidence_uses_filled_orders_and_invested_snapshots():
    evidence = build_behavior_evidence(FakeWorker().details("candidate-1"))
    assert evidence == {
        "order_count": 1,
        "filled_order_count": 1,
        "rejected_order_count": 0,
        "traded_symbols": ["MSFT"],
        "first_fill_time": "2024-01-02T16:00:00",
        "last_fill_time": "2024-01-02T16:00:00",
        "position_snapshot_count": 1,
        "invested_snapshot_count": 1,
        "max_gross_exposure": 0.5,
        "rebalance_count": 1,
    }


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


def test_acceptance_revision_enters_repair_then_reruns_and_revalidates():
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
    assert repairer.calls[0]["repair_trigger"] == "acceptance_revision"
    assert repairer.calls[0]["acceptance_report"]["checks"][1]["id"] == "A2"
    assert len(worker.custom_submissions) == 5


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
    assert all("A1 contradicts" in item["error"] for item in completed["candidates"])
    assert repairer.calls == []


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
