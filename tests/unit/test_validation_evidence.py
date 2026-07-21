from __future__ import annotations

from alphaforge.agents.providers.mock import MockBacktestProvider
from alphaforge.demo import build_demo_environment, build_demo_request
from backend.app.services.validation_evidence import ValidationEvidenceRunner


def test_validation_evidence_uses_one_parent_and_four_fixed_baselines() -> None:
    results = ValidationEvidenceRunner(
        backtest_provider=MockBacktestProvider(),
        lean_environment=build_demo_environment(),
    ).run(build_demo_request().parent_spec)
    assert tuple(result.strategy_role for result in results) == (
        "user",
        "baseline_b1",
        "baseline_b2",
        "baseline_b3",
        "baseline_b4",
    )
    assert len({result.run_id for result in results}) == 5
    assert all(result.provider == "mock_backtest" for result in results)
    assert all(result.dataset_split == "validation" for result in results)
