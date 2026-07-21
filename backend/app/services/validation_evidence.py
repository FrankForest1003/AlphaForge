from __future__ import annotations

from collections.abc import Callable

from alphaforge.codegen.code_validator import DEFAULT_ALLOWED_QC_API, validate_generated_code
from alphaforge.codegen.compiler import DeterministicStrategyCompiler
from alphaforge.codegen.template_renderer import QCTemplateRenderer
from alphaforge.ports import BacktestProvider
from alphaforge.schemas.agent_outputs import StrategyCompilationRequest
from alphaforge.schemas.backtest import BacktestResult
from alphaforge.schemas.manifests import LeanEnvironmentManifest
from alphaforge.schemas.strategy_spec import MLLogic, StrategySpec, TraditionalLogic
from alphaforge.strategy_spec.versioning import strategy_spec_digest


class ValidationEvidenceError(RuntimeError):
    pass


class ValidationEvidenceRunner:
    """Backtest the parent and four fixed baselines under one LEAN contract."""

    def __init__(
        self,
        *,
        backtest_provider: BacktestProvider,
        lean_environment: LeanEnvironmentManifest,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.backtest_provider = backtest_provider
        self.lean_environment = lean_environment
        self.progress = progress or (lambda _message: None)
        self.renderer = QCTemplateRenderer()
        self.compiler = DeterministicStrategyCompiler(self.renderer)

    def run(self, parent_spec: StrategySpec) -> tuple[BacktestResult, ...]:
        results: list[BacktestResult] = []
        for role, spec in self._specs(parent_spec):
            self.progress(f"validation evidence: compiling {role} ({spec.strategy_id})")
            route = spec.logic.kind
            request = StrategyCompilationRequest(
                strategy_spec=spec,
                spec_sha256=strategy_spec_digest(spec),
                lean_environment=self.lean_environment,
                allowed_qc_api=DEFAULT_ALLOWED_QC_API,
                template_version=self.renderer.template_version(route),
                template_sha256=self.renderer.template_sha256(route),
                semantics_version=self.renderer.SEMANTICS_VERSION,
            )
            code = self.compiler.compile(request)
            validation = validate_generated_code(
                spec,
                code,
                allowed_qc_api=DEFAULT_ALLOWED_QC_API,
                allowed_imports=self.lean_environment.allowed_imports,
            )
            if not validation.valid:
                raise ValidationEvidenceError(
                    f"{spec.strategy_id} static validation failed: {validation.errors}"
                )

            self.progress(f"validation evidence: smoke {role} ({spec.strategy_id})")
            smoke = self.backtest_provider.smoke_test(spec, code)
            if smoke.status != "passed":
                raise ValidationEvidenceError(
                    f"{spec.strategy_id} smoke failed: {smoke.diagnostics}"
                )

            self.progress(f"validation evidence: backtest {role} ({spec.strategy_id})")
            result = self.backtest_provider.run(spec, code)
            if result.status != "completed" or result.metrics is None:
                raise ValidationEvidenceError(
                    f"{spec.strategy_id} backtest failed: {result.warnings}"
                )
            results.append(
                result.model_copy(
                    update={
                        "strategy_role": role,
                        "dataset_split": "validation",
                    }
                )
            )
        return tuple(results)

    def _specs(self, parent: StrategySpec):
        definitions = (
            ("user", parent.strategy_id, parent.logic),
            (
                "baseline_b1",
                "baseline_b1_momentum_v1",
                TraditionalLogic(signal="momentum_rank", lookback_days=126),
            ),
            (
                "baseline_b2",
                "baseline_b2_mean_reversion_v1",
                TraditionalLogic(signal="mean_reversion_rank", lookback_days=20),
            ),
            (
                "baseline_b3",
                "baseline_b3_gbdt_v1",
                MLLogic(
                    model="gradient_boosting",
                    task="relative_alpha_regression",
                    training_window_days=504,
                    prediction_horizon_days=21,
                    feature_set_version="price_volume_v1",
                    random_seed=42,
                ),
            ),
            (
                "baseline_b4",
                "baseline_b4_rf_v1",
                MLLogic(
                    model="random_forest",
                    task="direction_classification",
                    training_window_days=504,
                    prediction_horizon_days=21,
                    feature_set_version="price_volume_v1",
                    random_seed=42,
                ),
            ),
        )
        for role, strategy_id, logic in definitions:
            payload = parent.model_dump(mode="python")
            payload.update(
                {
                    "strategy_id": strategy_id,
                    "parent_strategy_id": None if role == "user" else parent.strategy_id,
                    "candidate_type": "user" if role == "user" else logic.kind,
                    "logic": logic,
                }
            )
            yield role, StrategySpec.model_validate(payload)
