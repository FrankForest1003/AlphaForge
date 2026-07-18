from __future__ import annotations

import pytest
from pydantic import ValidationError

from alphaforge.demo import build_demo_request
from alphaforge.schemas.agent_outputs import CandidateDesign, ExecutionChanges, RiskChanges
from alphaforge.schemas.strategy_spec import MLLogic, TraditionalLogic
from alphaforge.services.spec_builder import SpecBuilder
from alphaforge.strategy_spec.validator import validate_strategy_spec


def test_candidate_design_rejects_extra_fields_and_string_reasons() -> None:
    payload = {
        "candidate_type": "traditional",
        "logic": {"kind": "traditional", "signal": "momentum_rank", "lookback_days": 126},
        "execution_changes": {"top_k": 4},
        "risk_changes": {},
        "design_reasons": "not-an-array",
        "expected_tradeoffs": ["higher turnover"],
        "strategy_id": "model-must-not-assign-this",
    }
    with pytest.raises(ValidationError):
        CandidateDesign.model_validate(payload)


def test_candidate_design_rejects_route_logic_mismatch() -> None:
    with pytest.raises(ValidationError, match="candidate_type must match logic.kind"):
        CandidateDesign(
            candidate_type="ml",
            logic=TraditionalLogic(signal="momentum_rank", lookback_days=126),
            execution_changes=ExecutionChanges(),
            risk_changes=RiskChanges(),
            design_reasons=("test",),
            expected_tradeoffs=("test",),
        )


def test_invalid_ml_task_is_rejected_without_default() -> None:
    with pytest.raises(ValidationError):
        MLLogic.model_validate(
            {
                "kind": "ml",
                "model": "gradient_boosting",
                "task": "classification",
                "training_window_days": 504,
                "prediction_horizon_days": 21,
                "feature_set_version": "features_v1",
                "random_seed": 42,
            }
        )


def test_spec_builder_preserves_fixed_fields_and_computes_diff() -> None:
    parent = build_demo_request().parent_spec
    design = CandidateDesign(
        candidate_type="traditional",
        logic=TraditionalLogic(signal="momentum_rank", lookback_days=126),
        execution_changes=ExecutionChanges(top_k=4),
        risk_changes=RiskChanges(),
        design_reasons=("respond faster to medium-term momentum",),
        expected_tradeoffs=("higher turnover",),
    )
    built = SpecBuilder().build(
        optimization_id="opt_001",
        parent_spec=parent,
        design=design,
    )
    assert built.spec.universe == parent.universe
    assert built.spec.risk == parent.risk
    assert built.spec.execution.start_date == parent.execution.start_date
    assert built.spec.execution.end_date == parent.execution.end_date
    assert built.spec.execution.initial_cash == parent.execution.initial_cash
    assert built.spec.execution.top_k == 4
    assert "/execution/top_k" in built.changed_paths
    assert "/logic/lookback_days" in built.changed_paths
    assert not validate_strategy_spec(
        built.spec,
        parent=parent,
        changed_paths=built.changed_paths,
    )
