from __future__ import annotations

import hashlib

from alphaforge.agents.providers.mock import MockStrategyDesigner
from alphaforge.codegen.compiler import DeterministicStrategyCompiler
from alphaforge.codegen.code_validator import DEFAULT_ALLOWED_QC_API, validate_generated_code
from alphaforge.codegen.template_renderer import QCTemplateRenderer
from alphaforge.demo import build_demo_environment, build_demo_request
from alphaforge.schemas.agent_outputs import DesignRequest, StrategyCompilationRequest
from alphaforge.services.evidence import EvidenceSummarizer
from alphaforge.services.spec_builder import SpecBuilder
from alphaforge.strategy_spec.versioning import strategy_spec_digest


def _valid_code():
    request = build_demo_request()
    design = MockStrategyDesigner().design(
        DesignRequest(
            optimization_id=request.optimization_id,
            candidate_type="traditional",
            round_number=1,
            parent_spec=request.parent_spec,
            constraints=request.constraints,
            evidence_summary=EvidenceSummarizer().summarize(
                request.evidence, request.reference_specs
            ),
        )
    )
    spec = SpecBuilder().build(
        optimization_id=request.optimization_id,
        parent_spec=request.parent_spec,
        design=design,
    ).spec
    renderer = QCTemplateRenderer()
    template_version = renderer.template_version("traditional")
    code = DeterministicStrategyCompiler(renderer).compile(
        StrategyCompilationRequest(
            strategy_spec=spec,
            spec_sha256=strategy_spec_digest(spec),
            lean_environment=build_demo_environment(),
            allowed_qc_api=DEFAULT_ALLOWED_QC_API,
            template_version=template_version,
            template_sha256=renderer.template_sha256("traditional"),
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


def test_uppercase_local_variables_are_not_treated_as_qc_api() -> None:
    spec, code = _valid_code()
    helper = '''    def build_training_set(self):
        X_parts = []
        X = pd.DataFrame()
        X_parts.append(X.index)
        labels = X.shift(-21)
        return X_parts, labels

'''
    source = code.source.replace("    def compute_scores(self):", helper + "    def compute_scores(self):")
    modified = code.model_copy(
        update={"source": source, "source_sha256": hashlib.sha256(source.encode()).hexdigest()}
    )
    result = validate_generated_code(spec, modified)
    assert result.valid
    assert not any("X.index" in error or "X_parts.append" in error for error in result.errors)


def test_negative_shift_outside_training_set_is_rejected() -> None:
    spec, code = _valid_code()
    source = code.source.replace(
        "    def compute_scores(self):",
        "    def build_features(self):\n        return pd.DataFrame().shift(-1)\n\n    def compute_scores(self):",
    )
    modified = code.model_copy(
        update={"source": source, "source_sha256": hashlib.sha256(source.encode()).hexdigest()}
    )
    result = validate_generated_code(spec, modified)
    assert not result.valid
    assert "POTENTIAL_LOOKAHEAD_SHIFT" in result.errors
