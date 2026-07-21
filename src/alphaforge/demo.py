from __future__ import annotations

from datetime import date

from alphaforge.schemas.backtest import BacktestMetrics, BacktestResult
from alphaforge.schemas.optimisation import OptimizationRequest
from alphaforge.schemas.manifests import LeanEnvironmentManifest
from alphaforge.schemas.strategy_spec import (
    ExecutionSpec,
    RiskConstraints,
    StrategySpec,
    TraditionalLogic,
    UniverseSpec,
)

SYMBOLS = (
    "MSFT",
    "AAPL",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "AVGO",
    "ASML",
    "AMD",
    "ORCL",
)


def build_demo_request(*, include_test_evidence: bool = False) -> OptimizationRequest:
    parent = StrategySpec(
        strategy_id="user_strategy_v1",
        candidate_type="user",
        universe=UniverseSpec(symbols=SYMBOLS),
        execution=ExecutionSpec(start_date=date(2018, 1, 1), end_date=date(2024, 12, 31)),
        risk=RiskConstraints(),
        logic=TraditionalLogic(signal="momentum_rank", lookback_days=252),
    )
    rows = (
        ("user", "user_strategy_v1", 0.98, 0.18, 0.11),
        ("baseline_b1", "baseline_b1_momentum_v1", 1.04, 0.19, 0.12),
        ("baseline_b2", "baseline_b2_mean_reversion_v1", 0.83, 0.14, 0.08),
        ("baseline_b3", "baseline_b3_gbdt_v1", 1.10, 0.22, 0.14),
        ("baseline_b4", "baseline_b4_rf_v1", 0.92, 0.16, 0.10),
    )
    evidence = tuple(
        BacktestResult(
            run_id=f"validation-{role}",
            strategy_id=strategy_id,
            strategy_role=role,
            status="completed",
            dataset_split="test" if include_test_evidence and role == "baseline_b4" else "validation",
            provider="fixture-v1",
            metrics=BacktestMetrics(
                cagr=cagr,
                sharpe_ratio=sharpe,
                sortino_ratio=sharpe * 1.25,
                max_drawdown=drawdown,
                annual_volatility=0.16,
                turnover=0.75,
                total_fees=100.0,
            ),
        )
        for role, strategy_id, sharpe, drawdown, cagr in rows
    )
    return OptimizationRequest(
        optimization_id="demo_opt_001",
        parent_spec=parent,
        evidence=evidence,
    )


def build_demo_environment() -> LeanEnvironmentManifest:
    return LeanEnvironmentManifest(
        provider="mock",
        lean_version="lean-test-v1",
        python_version="3.11",
        data_version="fixture-v1",
        brokerage_model="cash-long-only",
        fee_model="fixed-test-fees",
        slippage_model="fixed-test-slippage",
        time_zone="America/New_York",
        normalization_mode="raw",
        allowed_imports=(
            "AlgorithmImports",
            "alphaforge_base",
            "datetime",
            "numpy",
            "pandas",
            "sklearn",
        ),
        python_dependencies=("numpy", "pandas", "scikit-learn"),
        qc_api_profile="qc_api_v1",
        template_compatibility=(
            "traditional_local_lean_v1",
            "ml_local_lean_v1",
            "hybrid_local_lean_v1",
        ),
    )
