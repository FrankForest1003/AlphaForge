from __future__ import annotations

import hashlib

from alphaforge.agents.providers.mock import MockQCCodeAgent, MockStrategyDesigner
from alphaforge.codegen.code_validator import DEFAULT_ALLOWED_QC_API, validate_generated_code
from alphaforge.demo import build_demo_environment, build_demo_request
from alphaforge.schemas.agent_outputs import DesignRequest, QCCodeGenerationRequest
from alphaforge.services.evidence import EvidenceSummarizer
from alphaforge.services.spec_builder import SpecBuilder
from alphaforge.strategy_spec.versioning import strategy_spec_digest


def _valid_code():
    request = build_demo_request()
    design = MockStrategyDesigner().design(
        DesignRequest(
            optimization_id=request.optimization_id,
            candidate_type="traditional",
            parent_spec=request.parent_spec,
            evidence_summary=EvidenceSummarizer().summarize(request.evidence),
        )
    )
    spec = SpecBuilder().build(
        optimization_id=request.optimization_id,
        parent_spec=request.parent_spec,
        design=design,
    ).spec
    code = MockQCCodeAgent().generate(
        QCCodeGenerationRequest(
            strategy_spec=spec,
            spec_sha256=strategy_spec_digest(spec),
            lean_environment=build_demo_environment(),
            allowed_qc_api=DEFAULT_ALLOWED_QC_API,
            template_version="qc_template_v1",
        )
    )
    return spec, code


def test_observed_undeclared_qc_api_is_rejected() -> None:
    spec, code = _valid_code()
    source = code.source.replace(
        "        for ticker in",
        "        self.MarketOrder(\"SPY\", 1)\n        for ticker in",
    )
    modified = code.model_copy(
        update={
            "source": source,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        }
    )
    result = validate_generated_code(spec, modified)
    assert not result.valid
    assert "QC_API_NOT_ALLOWED_OBSERVED:MarketOrder" in result.errors
