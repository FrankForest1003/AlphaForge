from __future__ import annotations

from typing import Any

from alphaforge.agents.providers.mock import MockStrategyDesigner
from alphaforge.codegen.compiler import DeterministicStrategyCompiler
from alphaforge.codegen.template_renderer import QCTemplateRenderer
from alphaforge.demo import build_demo_request
from alphaforge.schemas.agent_outputs import DesignRequest, StrategyCompilationRequest
from alphaforge.services.evidence import EvidenceSummarizer
from alphaforge.services.spec_builder import SpecBuilder
from alphaforge.strategy_spec.versioning import strategy_spec_digest
from backend.app.services import LeanWorkerClient, LocalLeanBacktestProvider, local_lean_environment_manifest


def _compiled_traditional():
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
    code = DeterministicStrategyCompiler(renderer).compile(
        StrategyCompilationRequest(
            strategy_spec=spec,
            spec_sha256=strategy_spec_digest(spec),
            lean_environment=local_lean_environment_manifest(),
            allowed_qc_api=renderer.BASE_QC_API,
            template_version=renderer.template_version("traditional"),
            template_sha256=renderer.template_sha256("traditional"),
        )
    )
    return spec, code


class RecordingClient(LeanWorkerClient):
    def __init__(self) -> None:
        super().__init__(token="test-token", poll_interval_seconds=0)
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def _request(self, method, path, payload=None, *, authenticated=True):
        self.calls.append((method, path, payload))
        return {"status": "deployed"}


def test_deployment_sends_digest_bound_source_and_benchmark_symbol() -> None:
    spec, code = _compiled_traditional()
    client = RecordingClient()
    client.deploy(spec, code)
    method, path, payload = client.calls[0]
    assert (method, path) == ("POST", "/v1/strategies/generated")
    assert payload is not None
    assert payload["source_sha256"] == code.source_sha256
    assert payload["spec_sha256"] == code.spec_sha256
    assert payload["algorithm_class"] == code.compiler_metadata["algorithm_class"]
    assert "SPY" in payload["required_symbols"]


class CompletedWorker:
    def __init__(self) -> None:
        self.submissions = 0

    def health(self):
        return {"status": "ok"}

    def deploy(self, spec, code):
        return {"status": "deployed"}

    def data_status(self):
        return {"ready": True, "common_end_date": "2024-12-31"}

    def submit(self, strategy_id, *, parameters=None, timeout_seconds=3600):
        self.submissions += 1
        return {"run_id": f"run-{self.submissions}"}

    def wait(self, run_id, *, deadline_seconds=4200):
        return {"state": "completed"}

    def result(self, run_id):
        return {
            "evaluation": {"eligible_for_comparison": True, "rejection_reasons": []},
            "summary": {
                "cagr": 0.12,
                "sharpe_ratio": 1.1,
                "sortino_ratio": 1.4,
                "maximum_drawdown": 0.18,
                "portfolio_turnover": 0.75,
                "total_fees": 123.0,
            },
            "statistics": {"annual_standard_deviation": 0.16},
        }


def test_local_lean_provider_normalizes_worker_result_contract() -> None:
    spec, code = _compiled_traditional()
    provider = LocalLeanBacktestProvider(CompletedWorker())
    assert provider.smoke_test(spec, code).status == "passed"
    result = provider.run(spec, code)
    assert result.status == "completed"
    assert result.metrics is not None
    assert result.metrics.sharpe_ratio == 1.1
    assert result.metrics.max_drawdown == 0.18
    assert result.provider == "local_lean_worker_v1.1.3"
