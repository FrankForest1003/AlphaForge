from __future__ import annotations

import hashlib

import pytest

from alphaforge.agents.providers.mock import MockStrategyDesigner
from alphaforge.codegen.compiler import DeterministicStrategyCompiler
from alphaforge.codegen.template_renderer import QCTemplateRenderer, TemplateRenderError, build_code_region
from alphaforge.demo import build_demo_environment, build_demo_request
from alphaforge.schemas.agent_outputs import DesignRequest, StrategyCompilationRequest
from alphaforge.services.evidence import EvidenceSummarizer
from alphaforge.services.spec_builder import SpecBuilder
from alphaforge.strategy_spec.versioning import strategy_spec_digest


def _spec(route: str):
    request = build_demo_request()
    design = MockStrategyDesigner().design(
        DesignRequest(
            optimization_id=request.optimization_id,
            candidate_type=route,
            round_number=1,
            parent_spec=request.parent_spec,
            constraints=request.constraints,
            evidence_summary=EvidenceSummarizer().summarize(
                request.evidence, request.reference_specs
            ),
        )
    )
    return SpecBuilder().build(
        optimization_id=request.optimization_id,
        parent_spec=request.parent_spec,
        design=design,
    ).spec


def _generation_request(route: str):
    spec = _spec(route)
    renderer = QCTemplateRenderer()
    version = renderer.template_version(route)
    return StrategyCompilationRequest(
        strategy_spec=spec,
        spec_sha256=strategy_spec_digest(spec),
        lean_environment=build_demo_environment(),
        allowed_qc_api=renderer.BASE_QC_API,
        template_version=version,
        template_sha256=renderer.template_sha256(route),
    )


@pytest.mark.parametrize("route", ("traditional", "ml", "hybrid"))
def test_deterministic_compiler_uses_strict_route_template(route: str) -> None:
    generated = DeterministicStrategyCompiler().compile(_generation_request(route))
    renderer = QCTemplateRenderer()
    assert tuple(region.name for region in generated.regions) == renderer.REQUIRED_REGIONS[route]
    assert "(AlphaForgeBaseAlgorithm):" in generated.source
    assert "def initialize_strategy(self):" in generated.source
    assert "def rebalance(self):" in generated.source
    assert "DataNormalizationMode.RAW" in generated.source
    assert "self.af_rebalance_to_weights(" in generated.source
    assert "max_drawdown_limit" not in generated.source
    assert generated.compiler_metadata["component"] == "strategy_engine.compiler"
    assert generated.compiler_metadata["runtime_contract"] == "local_lean_v1.1.3"
    if route in {"ml", "hybrid"}:
        assert "GradientBoostingRegressor" in generated.source
        assert 'features["return_126d"] = close.pct_change(126)' in generated.source
        assert 'dataset.dropna(subset=[*columns, "label"])' in generated.source


def test_renderer_rejects_missing_unknown_and_digest_mismatched_regions() -> None:
    renderer = QCTemplateRenderer()
    spec = _spec("traditional")
    with pytest.raises(TemplateRenderError, match="region mismatch"):
        renderer.render(spec, ())
    unknown = build_code_region("unknown", "def unknown(self):\n    return {}")
    with pytest.raises(TemplateRenderError, match="region mismatch"):
        renderer.render(spec, (unknown,))
    valid = build_code_region(
        "compute_traditional_scores",
        "def compute_traditional_scores(self):\n    return {}",
    )
    invalid = valid.model_copy(update={"source_sha256": hashlib.sha256(b"wrong").hexdigest()})
    with pytest.raises(TemplateRenderError, match="digest mismatch"):
        renderer.render(spec, (invalid,))
