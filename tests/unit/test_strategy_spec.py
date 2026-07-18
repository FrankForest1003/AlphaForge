from __future__ import annotations

import pytest
from pydantic import ValidationError

from alphaforge.demo import build_demo_request
from alphaforge.schemas.agent_outputs import CandidateProposal
from alphaforge.schemas.manifests import LeanEnvironmentManifest
from alphaforge.schemas.strategy_spec import RiskConstraints
from alphaforge.strategy_spec.codec import CanonicalJsonCodec
from alphaforge.strategy_spec.validator import validate_strategy_spec


def test_canonical_json_codec_round_trip() -> None:
    original = build_demo_request().parent_spec
    codec = CanonicalJsonCodec()
    assert codec.decode(codec.encode(original)) == original


def test_position_cap_above_frozen_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RiskConstraints(max_position_weight=0.36)


def test_agent_cannot_change_universe() -> None:
    parent = build_demo_request().parent_spec
    candidate = parent.model_copy(
        update={
            "strategy_id": "candidate_traditional_v1",
            "parent_strategy_id": parent.strategy_id,
            "candidate_type": "traditional",
            "universe": parent.universe.model_copy(
                update={"symbols": parent.universe.symbols[:-1] + ("JPM",)}
            ),
        }
    )
    proposal = CandidateProposal(
        candidate_type="traditional",
        spec=candidate,
        changed_paths=("/universe/symbols",),
        design_reasons=("test",),
        expected_tradeoffs=("test",),
    )
    issues = validate_strategy_spec(candidate, parent=parent, proposal=proposal)
    assert {issue.code for issue in issues} == {
        "CHANGE_SCOPE_FORBIDDEN",
        "UNIVERSE_CHANGE_FORBIDDEN",
    }


def test_environment_manifest_keeps_open_execution_choices_explicit() -> None:
    manifest = LeanEnvironmentManifest(
        provider="local_lean",
        lean_version="OPEN-03-not-frozen",
        python_version="3.11",
        data_version="catalog_v0",
        brokerage_model="OPEN-05-not-frozen",
        fee_model="OPEN-05-not-frozen",
        slippage_model="OPEN-05-not-frozen",
        time_zone="OPEN-05-not-frozen",
    )
    assert manifest.fee_model.startswith("OPEN-05")
