from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

import app.services.baseline_service as service_module
from agent import DeepSeekCritic, DeepSeekDesigner
from agent.critic import build_metric_comparisons
from agent.prompts import PARAMETER_RULES, TRACK_SPEC_EXAMPLES
from app.schemas import CritiqueReport, RunSettings, StrategyTemplateSpec
from app.services.baseline_service import ForgeService
from app.services.worker_client import LeanWorkerPoolClient, WorkerClientError


def traditional_spec(window: int = 126) -> dict:
    return {
        "schema_version": "template-v1",
        "strategy_name": f"Transparent Rank {window}",
        "track": "Traditional",
        "thesis": "A diversified transparent rank can improve risk adjusted returns.",
        "signal": {
            "components": [
                {
                    "feature": {"kind": "return", "window": window},
                    "direction": "higher",
                    "weight": 0.7,
                },
                {
                    "feature": {"kind": "volatility", "window": 42},
                    "direction": "lower",
                    "weight": 0.3,
                },
            ]
        },
        "selection": {"top_k": 5},
        "portfolio": {
            "weighting": "inverse_volatility",
            "gross_exposure": 0.9,
            "max_position_weight": 0.25,
        },
        "schedule": {"frequency": "monthly"},
        "risk": {"market_trend_filter": True, "market_sma_window": 180},
    }


def proposal(window: int = 126) -> dict:
    return {
        "design": {
            "reference_baselines": ["Momentum Rank"],
            "improvement_hypothesis": "Volatility weighting may reduce concentration risk.",
            "differentiation": ["adds a volatility rank", "uses five holdings"],
            "expected_tradeoff": "Diversification may reduce upside in concentrated rallies.",
        },
        "strategy_spec": traditional_spec(window),
    }


class Completions:
    def __init__(self, payload: dict):
        self.payload = payload
        self.request = None

    def create(self, **request):
        self.request = request
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(self.payload))
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=40,
                completion_tokens=20,
                total_tokens=60,
            ),
        )


def client_for(payload: dict):
    completions = Completions(payload)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def settings() -> dict:
    return {
        "symbols": ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
        "start_date": "2020-01-02",
        "end_date": "2024-12-31",
        "benchmark": "SPY",
        "transaction_cost_bps": 10,
        "slippage_bps": 5,
    }


def test_designer_returns_parameters_and_prompt_contains_no_python_context():
    client, completions = client_for(proposal())
    designer = DeepSeekDesigner(
        api_key="test",
        base_url="https://example.invalid",
        model="test-model",
        thinking_enabled=False,
        client=client,
    )

    result = designer.generate(
        track="Traditional",
        run_settings=settings(),
        baseline_results=[{"name": "Momentum Rank", "family": "Traditional"}],
    )

    prompt = completions.request["messages"][1]["content"]
    assert result["strategy_spec"]["track"] == "Traditional"
    assert "source_code" not in result
    assert "AlgorithmImports" not in prompt
    assert "QuantConnect" not in prompt
    assert "lean_documentation" not in prompt
    assert '"valid_strategy_spec_example"' in prompt
    assert '"parameter_rules"' in prompt
    assert '"feature.kind"' not in prompt


@pytest.mark.parametrize("track", ["Traditional", "ML", "Hybrid"])
def test_prompt_track_examples_are_directly_schema_valid(track):
    validated = StrategyTemplateSpec.model_validate(TRACK_SPEC_EXAMPLES[track])
    payload = validated.model_dump(mode="json")

    assert payload["track"] == track
    serialized = json.dumps(TRACK_SPEC_EXAMPLES[track])
    assert '"rule"' not in serialized
    assert '"constraint"' not in serialized
    assert '"feature.kind"' not in serialized


def test_designer_revision_must_change_parameters():
    with pytest.raises(ValueError, match="must change"):
        DeepSeekDesigner._validated_proposal(
            proposal(),
            "Traditional",
            symbol_count=5,
            previous_spec=traditional_spec(),
        )


def test_designer_preserves_valid_spec_and_compacts_cosmetic_design_metadata():
    payload = proposal()
    payload["design"]["differentiation"] = ["one", "two", "three", "four"]

    normalized = DeepSeekDesigner._validated_proposal(
        payload,
        "Traditional",
        symbol_count=5,
    )

    assert normalized["strategy_spec"] == StrategyTemplateSpec.model_validate(
        traditional_spec()
    ).model_dump(mode="json")
    assert normalized["design"]["differentiation"] == ["one", "two", "three"]


def test_critic_returns_advice_not_replacement_parameters():
    payload = {
        "iteration": 1,
        "diagnosis": "Return is competitive but drawdown is above the public reference.",
        "strengths": ["Positive risk-adjusted return"],
        "weaknesses": ["Maximum drawdown remains high"],
        "preserve": ["transparent momentum component"],
        "recommended_changes": [
            {
                "field": "portfolio.gross_exposure",
                "direction": "decrease",
                "reason": "Lower exposure directly targets the observed drawdown.",
            }
        ],
        "overfitting_warning": "Judge this one bounded change across robustness tests.",
    }
    client, completions = client_for(payload)
    critic = DeepSeekCritic(
        api_key="test",
        base_url="https://example.invalid",
        model="test-model",
        thinking_enabled=False,
        client=client,
    )

    result = critic.evaluate(
        track="Traditional",
        iteration=1,
        strategy_spec=traditional_spec(),
        iteration_result={"iteration": 1, "summary": {"sharpe_ratio": 1.0}},
        baseline_results=[{"name": "Momentum Rank", "family": "Traditional"}],
        iteration_history=[],
    )

    assert CritiqueReport.model_validate(result["report"])
    assert "strategy_spec" not in result["report"]
    assert "source_code" not in completions.request["messages"][1]["content"]


def test_critic_discards_inactive_ml_fields_and_uses_precomputed_comparisons():
    payload = {
        "iteration": 1,
        "diagnosis": "The completed ML trial trails the strongest public Sharpe ratio.",
        "strengths": ["The model training path completed."],
        "weaknesses": ["Risk adjusted return trails the public reference."],
        "preserve": ["regularized model"],
        "recommended_changes": [
            {
                "field": "strategy_spec.selection.hybrid_model_weight",
                "direction": "increase",
                "reason": "Increase the hybrid contribution.",
            },
            {
                "field": "strategy_spec.model.ridge_alpha",
                "direction": "increase",
                "reason": "Test stronger regularization.",
            },
        ],
        "overfitting_warning": "Do not select parameters from one favorable trial.",
    }
    ml = dict(TRACK_SPEC_EXAMPLES["ML"])
    client, completions = client_for(payload)
    critic = DeepSeekCritic(
        api_key="test",
        base_url="https://example.invalid",
        model="test-model",
        thinking_enabled=False,
        client=client,
    )

    result = critic.evaluate(
        track="ML",
        iteration=1,
        strategy_spec=ml,
        iteration_result={"summary": {"sharpe_ratio": 0.8, "cagr": 0.1}},
        baseline_results=[
            {"name": "Gradient Boosting", "summary": {"sharpe_ratio": 1.0}}
        ],
        iteration_history=[],
    )

    assert [
        change["field"] for change in result["report"]["recommended_changes"]
    ] == ["model.ridge_alpha"]
    assert result["discarded_recommendations"][0]["field"] == (
        "selection.hybrid_model_weight"
    )
    prompt = completions.request["messages"][1]["content"]
    assert '"computed_comparisons"' in prompt
    assert "hybrid-decision counters should be zero" in prompt


def test_metric_comparisons_use_lower_drawdown_as_best_public_value():
    comparisons = build_metric_comparisons(
        {"summary": {"maximum_drawdown": 0.25}},
        [
            {"name": "A", "summary": {"maximum_drawdown": 0.30}},
            {"name": "B", "summary": {"maximum_drawdown": 0.20}},
        ],
        [{"summary": {"maximum_drawdown": 0.27}}],
    )

    drawdown = comparisons["maximum_drawdown"]
    assert drawdown["best_public_baseline_name"] == "B"
    assert drawdown["current_minus_best_public"] == pytest.approx(0.05)
    assert drawdown["current_minus_previous"] == pytest.approx(-0.02)


def test_parameter_rules_expose_previously_missed_numeric_bounds():
    rules = " ".join(PARAMETER_RULES)
    assert "ridge_alpha 0.01-100" in rules
    assert "gross_exposure 0.50-0.98" in rules


def test_forge_runs_three_parameter_iterations_and_retains_best():
    summaries = [
        {
            "cagr": 0.10,
            "sharpe_ratio": 0.8,
            "maximum_drawdown": 0.20,
            "end_equity": 120_000,
        },
        {
            "cagr": 0.13,
            "sharpe_ratio": 1.2,
            "maximum_drawdown": 0.18,
            "end_equity": 130_000,
        },
        {
            "cagr": 0.16,
            "sharpe_ratio": 1.0,
            "maximum_drawdown": 0.17,
            "end_equity": 140_000,
        },
    ]

    class Worker:
        def __init__(self):
            self.count = 0

        def submit_custom(self, source, parameters):
            self.count += 1
            return {"run_id": f"worker-{self.count}"}

        def job(self, run_id):
            return {"state": "completed", "result_path": "result.json"}

        def result(self, run_id):
            index = int(run_id.rsplit("-", 1)[1]) - 1
            return {
                "status": "completed",
                "summary": summaries[index],
                "errors": [],
            }

        def details(self, run_id):
            raise RuntimeError("details omitted in unit test")

    class Designer:
        def __init__(self):
            self.windows = iter((63, 252))

        def generate(self, **kwargs):
            return {**proposal(next(self.windows)), "usage": {}}

    class Critic:
        def evaluate(self, **kwargs):
            iteration = kwargs["iteration"]
            return {
                "report": {
                    "iteration": iteration,
                    "diagnosis": "Completed trial with comparable performance evidence.",
                    "strengths": ["The parameter set completed the LEAN backtest."],
                    "weaknesses": ["Risk-adjusted return can still be compared."],
                    "preserve": ["transparent signal design"],
                    "recommended_changes": [],
                    "overfitting_warning": "Three trials are exploratory, not proof.",
                },
                "usage": {},
                "trace": {},
            }

    run_settings = RunSettings(
        symbols=["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
        start_date="2020-01-02",
        end_date="2024-12-31",
        initial_cash=100_000,
        benchmark="SPY",
        transaction_cost_bps=10,
        slippage_bps=5,
    )
    service = ForgeService(
        worker=Worker(),
        designer=Designer(),
        critic=Critic(),
        allowed_symbols=set(run_settings.symbols),
        allowed_benchmarks={"SPY"},
    )
    run_id = "forge-test"
    service._runs[run_id] = {
        "settings": run_settings.model_dump(mode="json"),
        "candidates": [{"track": "Traditional"}],
        "updated_at": "",
    }
    service._traces[run_id] = {
        "agent_calls": [],
        "worker_attempts": [],
        "updated_at": "",
    }

    service._run_template_candidate(
        run_id=run_id,
        index=0,
        track="Traditional",
        settings=run_settings,
        parameters=run_settings.worker_parameters(),
        baseline_results=[],
        initial_proposal={**proposal(126), "usage": {}},
    )

    candidate = service._runs[run_id]["candidates"][0]
    assert candidate["state"] == "accepted"
    assert candidate["iteration_count"] == 3
    assert candidate["best_iteration"] == 2
    assert candidate["summary"]["sharpe_ratio"] == 1.2
    assert len(candidate["critique_history"]) == 3
    assert all(item["strategy_spec"] for item in candidate["iterations"])
    service._executor.shutdown(wait=True)


def test_forge_preserves_best_completed_iteration_when_later_worker_poll_fails():
    summaries = [
        {"cagr": 0.10, "sharpe_ratio": 0.8, "maximum_drawdown": 0.20},
        {"cagr": 0.12, "sharpe_ratio": 1.1, "maximum_drawdown": 0.18},
    ]

    class Worker:
        def __init__(self):
            self.count = 0

        def submit_custom(self, source, parameters):
            self.count += 1
            return {"run_id": f"worker-{self.count}"}

        def job(self, run_id):
            if run_id == "worker-3":
                raise RuntimeError("temporary worker index failure")
            return {"state": "completed", "result_path": "result.json"}

        def result(self, run_id):
            index = int(run_id.rsplit("-", 1)[1]) - 1
            return {"status": "completed", "summary": summaries[index], "errors": []}

        def details(self, run_id):
            raise RuntimeError("details omitted")

    class Designer:
        def __init__(self):
            self.windows = iter((63, 252))

        def generate(self, **kwargs):
            return {**proposal(next(self.windows)), "usage": {}}

    class Critic:
        def evaluate(self, **kwargs):
            iteration = kwargs["iteration"]
            return {
                "report": {
                    "iteration": iteration,
                    "diagnosis": "The completed result is available for comparison.",
                    "strengths": ["The fixed template completed."],
                    "weaknesses": [],
                    "preserve": [],
                    "recommended_changes": [],
                    "overfitting_warning": "Treat the limited trials as exploratory.",
                },
                "usage": {},
            }

    run_settings = RunSettings(
        symbols=["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
        start_date="2020-01-02",
        end_date="2024-12-31",
        initial_cash=100_000,
        benchmark="SPY",
        transaction_cost_bps=10,
        slippage_bps=5,
    )
    service = ForgeService(
        worker=Worker(),
        designer=Designer(),
        critic=Critic(),
        allowed_symbols=set(run_settings.symbols),
        allowed_benchmarks={"SPY"},
    )
    service._runs["forge-partial"] = {
        "settings": run_settings.model_dump(mode="json"),
        "candidates": [{"track": "Traditional"}],
        "updated_at": "",
    }
    service._traces["forge-partial"] = {
        "agent_calls": [],
        "worker_attempts": [],
        "updated_at": "",
    }

    service._run_template_candidate(
        run_id="forge-partial",
        index=0,
        track="Traditional",
        settings=run_settings,
        parameters=run_settings.worker_parameters(),
        baseline_results=[],
        initial_proposal={**proposal(126), "usage": {}},
    )

    candidate = service._runs["forge-partial"]["candidates"][0]
    assert candidate["state"] == "accepted"
    assert candidate["best_iteration"] == 2
    assert candidate["attempted_iteration_count"] == 3
    assert candidate["partial_completion"] is True
    assert "temporary worker index failure" in candidate["partial_completion_reason"]
    service._executor.shutdown(wait=True)


def test_wait_for_worker_retries_only_transient_unknown_run(monkeypatch):
    class Worker:
        def __init__(self):
            self.polls = 0

        def job(self, run_id):
            self.polls += 1
            if self.polls < 3:
                raise WorkerClientError(
                    "unknown",
                    status_code=404,
                    response_text='{"detail":"Unknown run_id"}',
                )
            return {"state": "completed", "result_path": "result.json"}

        def result(self, run_id):
            return {"status": "completed", "summary": {}, "errors": []}

        def details(self, run_id):
            raise RuntimeError("details omitted")

    worker = Worker()
    service = ForgeService(
        worker=worker,
        designer=object(),
        critic=object(),
        allowed_symbols={"MSFT"},
        allowed_benchmarks={"SPY"},
    )
    service._runs["retry"] = {
        "settings": {"initial_cash": 100000},
        "candidates": [{}],
        "updated_at": "",
    }
    monkeypatch.setattr("app.services.baseline_service.time.sleep", lambda _: None)

    result = service._wait_for_worker("retry", "candidates", 0, "worker-1")

    assert result["status"] == "completed"
    assert worker.polls == 3
    service._executor.shutdown(wait=True)


def test_worker_pool_routes_every_job_back_to_its_original_slot():
    class Worker:
        def __init__(self, name):
            self.name = name
            self.submitted = []
            self.polled = []

        def submit(self, strategy_id, parameters):
            run_id = f"{self.name}-{len(self.submitted) + 1}"
            self.submitted.append(run_id)
            return {"run_id": run_id, "state": "queued"}

        def job(self, run_id):
            self.polled.append(run_id)
            return {"state": "completed", "result_path": "result.json"}

        def result(self, run_id):
            return {"status": "completed", "run_id": run_id}

        def health(self):
            return {"status": "ok"}

    first = Worker("first")
    second = Worker("second")
    pool = LeanWorkerPoolClient([first, second])

    a = pool.submit("a", {})
    b = pool.submit("b", {})
    c = pool.submit("c", {})
    assert a["run_id"].startswith("worker-1::first-")
    assert b["run_id"].startswith("worker-2::second-")
    assert c["run_id"].startswith("worker-1::first-")

    pool.job(b["run_id"])
    d = pool.submit("d", {})
    assert d["run_id"].startswith("worker-2::second-")
    assert pool.result(a["run_id"])["run_id"] == "first-1"
    assert first.polled == []
    assert second.polled == ["second-1"]

    health = pool.health()
    assert health["status"] == "ok"
    assert health["worker_count"] == 2
    assert health["ready_workers"] == 2


def test_execute_parallelizes_baselines_and_candidate_tracks(monkeypatch):
    baseline_barrier = threading.Barrier(4)
    candidate_barrier = threading.Barrier(3)

    class Designer:
        def generate(self, **kwargs):
            track = kwargs["track"]
            return {
                "design": {
                    "reference_baselines": ["Momentum Rank"],
                    "improvement_hypothesis": "A bounded alternative may improve results.",
                    "differentiation": ["Uses a distinct parameter set."],
                    "expected_tradeoff": "Improvement may increase estimation risk.",
                },
                "strategy_spec": TRACK_SPEC_EXAMPLES[track],
                "usage": {},
                "trace": {},
            }

    run_settings = RunSettings(
        symbols=["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"],
        start_date="2020-01-02",
        end_date="2024-12-31",
        initial_cash=100_000,
        benchmark="SPY",
        transaction_cost_bps=10,
        slippage_bps=5,
    )
    service = ForgeService(
        worker=object(),
        designer=Designer(),
        critic=object(),
        allowed_symbols=set(run_settings.symbols),
        allowed_benchmarks={"SPY"},
    )
    run_id = "forge-parallel"
    service._runs[run_id] = {
        "run_id": run_id,
        "state": "queued",
        "stage": "",
        "settings": run_settings.model_dump(mode="json"),
        "baselines": [
            {
                "name": item["name"],
                "family": item["family"],
                "state": "waiting",
                "summary": {},
                "analysis": {},
                "behavior_evidence": {},
            }
            for item in service_module.BASELINES
        ],
        "human": {
            "state": "waiting",
            "summary": {},
            "analysis": {},
            "behavior_evidence": {},
        },
        "candidates": [
            {
                "track": track,
                "state": "waiting",
                "summary": {},
                "analysis": {},
                "behavior_evidence": {},
                "iterations": [],
            }
            for track in ("Traditional", "ML", "Hybrid")
        ],
        "updated_at": "",
        "battle_analysis": None,
    }
    service._traces[run_id] = {
        "agent_calls": [],
        "worker_attempts": [],
        "updated_at": "",
    }

    def fake_baseline(*, run_id, index, parameters):
        baseline_barrier.wait(timeout=2)
        item = service_module.BASELINES[index]
        return {
            "name": item["name"],
            "family": item["family"],
            "summary": {
                "sharpe_ratio": 0.5 + index / 10,
                "cagr": 0.1 + index / 100,
                "maximum_drawdown": 0.2 + index / 100,
            },
            "performance_profile": {},
            "execution_profile": {},
            "public_lesson": {},
        }

    def fake_human(**kwargs):
        service._change_human(run_id, state="completed")

    def fake_candidate(*, index, track, **kwargs):
        candidate_barrier.wait(timeout=2)
        service._change_item(
            run_id,
            "candidates",
            index,
            state="accepted",
            summary={"sharpe_ratio": 1.0, "cagr": 0.2, "maximum_drawdown": 0.15},
        )

    monkeypatch.setattr(service, "_run_public_baseline", fake_baseline)
    monkeypatch.setattr(service, "_run_human", fake_human)
    monkeypatch.setattr(service, "_run_template_candidate", fake_candidate)
    monkeypatch.setattr(service, "_persist_history", lambda _: None)
    monkeypatch.setattr(
        service_module,
        "build_battle_analysis",
        lambda run: {"parallel_test": True},
    )

    service._execute(run_id, run_settings, "ignored")

    run = service._runs[run_id]
    assert run["state"] == "completed"
    assert [item["name"] for item in service._traces[run_id]["baseline_results"]] == [
        item["name"] for item in service_module.BASELINES
    ]
    assert all(item["state"] == "accepted" for item in run["candidates"])
    assert run["battle_analysis"] == {"parallel_test": True}
    service._executor.shutdown(wait=True)
