from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphaforge.schemas.agent_outputs import (
    CandidateDesign,
    CodeRiskReview,
    GeneratedCode,
    PostBacktestAnalysis,
    SelectionResult,
    TemplateCapabilityReport,
)
from alphaforge.agents.context import AgentContextBundle


EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "api" / "examples"


@pytest.mark.parametrize(
    ("filename", "model"),
    (
        ("CandidateDesign.json", CandidateDesign),
        ("GeneratedCode.json", GeneratedCode),
        ("CodeRiskReview.json", CodeRiskReview),
        ("PostBacktestAnalysis.json", PostBacktestAnalysis),
        ("SelectionResult.json", SelectionResult),
        ("AgentContextBundle.json", AgentContextBundle),
        ("TemplateCapabilityReport.json", TemplateCapabilityReport),
    ),
)
def test_documented_json_examples_match_their_schema(filename, model) -> None:
    payload = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    model.model_validate(payload)
