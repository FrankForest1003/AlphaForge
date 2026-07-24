from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import DeepSeekCritic, DeepSeekDesigner
from app.schemas import CritiqueReport, RunSettings
from app.services.baseline_service import ForgeService


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
    assert '"strategy_dsl"' in prompt


def test_designer_revision_must_change_parameters():
    with pytest.raises(ValueError, match="must change"):
        DeepSeekDesigner._validated_proposal(
            proposal(),
            "Traditional",
            symbol_count=5,
            previous_spec=traditional_spec(),
        )


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
