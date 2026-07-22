from __future__ import annotations

import ast
import hashlib
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from alphaforge.schemas.agent_outputs import CodeRegion
from alphaforge.schemas.strategy_spec import HybridLogic, MLLogic, StrategySpec


class TemplateRenderError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedTemplate:
    source: str
    source_sha256: str
    template_version: str
    template_sha256: str


class QCTemplateRenderer:
    """Render Local LEAN lifecycle code around deterministic strategy regions."""

    SEMANTICS_VERSION = "qc_semantics_v1"
    REQUIRED_REGIONS = {
        "traditional": ("compute_traditional_scores",),
        "ml": ("build_features", "build_training_set", "fit_model", "predict_scores"),
        "hybrid": (
            "compute_traditional_scores",
            "build_features",
            "build_training_set",
            "fit_model",
            "predict_scores",
            "combine_scores",
        ),
    }
    BASE_QC_API = (
        "AlphaForgeBaseAlgorithm",
        "get_parameter",
        "debug",
        "set_start_date",
        "set_end_date",
        "set_cash",
        "add_equity",
        "history",
        "schedule.on",
        "date_rules.month_start",
        "time_rules.after_market_open",
        "Resolution.DAILY",
        "DataNormalizationMode.RAW",
        "set_warm_up",
        "af_track_symbol",
        "af_use_security_benchmark",
        "af_record_signal",
        "af_record_ml_training",
        "af_record_ml_prediction",
        "af_rebalance_to_weights",
    )

    def __init__(self) -> None:
        self.asset_root = Path(__file__).parents[1] / "templates"

    def template_version(self, candidate_type: str) -> str:
        route = "traditional" if candidate_type == "user" else candidate_type
        if route not in self.REQUIRED_REGIONS:
            raise TemplateRenderError(f"unsupported candidate type: {candidate_type}")
        return f"{route}_local_lean_v1"

    def template_sha256(self, candidate_type: str) -> str:
        route = "traditional" if candidate_type == "user" else candidate_type
        common, route_template = self._template_text(route)
        return hashlib.sha256((common + "\n" + route_template).encode("utf-8")).hexdigest()

    def render(self, spec: StrategySpec, regions: tuple[CodeRegion, ...]) -> RenderedTemplate:
        route = spec.logic.kind
        if route not in self.REQUIRED_REGIONS:
            raise TemplateRenderError(f"unsupported candidate type: {route}")
        expected = self.REQUIRED_REGIONS[route]
        supplied = tuple(region.name for region in regions)
        if len(set(supplied)) != len(supplied):
            raise TemplateRenderError("duplicate generated region")
        missing = sorted(set(expected) - set(supplied))
        extra = sorted(set(supplied) - set(expected))
        if missing or extra:
            raise TemplateRenderError(f"region mismatch; missing={missing}, extra={extra}")

        common, route_template = self._template_text(route)
        by_name = {region.name: region for region in regions}
        for name in expected:
            region = by_name[name]
            self._validate_region(region)
            route_template = route_template.replace(
                f"__REGION_{name}__", textwrap.indent(region.source.strip(), "    ")
            )
        if "__REGION_" in route_template:
            raise TemplateRenderError("unresolved route template marker")

        logic = spec.logic.ml if isinstance(spec.logic, HybridLogic) else spec.logic
        source = common
        replacements = {
            "__START_DATE__": spec.execution.start_date.isoformat(),
            "__END_DATE__": spec.execution.end_date.isoformat(),
            "__INITIAL_CASH__": repr(float(spec.execution.initial_cash)),
            "__SYMBOLS__": repr(list(spec.universe.symbols)),
            "__TOP_K__": str(spec.execution.top_k),
            "__TARGET_GROSS__": repr(spec.execution.target_gross),
            "__REGIME_FILTER__": spec.execution.regime_filter,
            "__REGIME_LOOKBACK_DAYS__": repr(spec.execution.regime_lookback_days),
            "__MAX_POSITION_WEIGHT__": repr(spec.risk.max_position_weight),
            "__WARMUP_DAYS__": str(self._warmup_days(spec)),
            "__ALGORITHM_CLASS__": self.algorithm_class(spec.strategy_id),
            "__COMPLETION_MARKER__": self.completion_marker(spec.strategy_id),
            "__MODEL_IMPORT__": self._model_import(logic if isinstance(logic, MLLogic) else None),
            "__ROUTE_METHODS__": route_template.rstrip(),
        }
        for marker, value in replacements.items():
            source = source.replace(marker, value)
        if "__" in source:
            unresolved = sorted({part for part in source.split() if part.startswith("__")})
            raise TemplateRenderError(f"unresolved common template marker: {unresolved}")
        source = source.rstrip() + "\n"
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise TemplateRenderError(f"rendered template is invalid Python: {exc}") from exc
        return RenderedTemplate(
            source=source,
            source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            template_version=self.template_version(route),
            template_sha256=self.template_sha256(route),
        )

    def _template_text(self, candidate_type: str) -> tuple[str, str]:
        common = (self.asset_root / "common_v1.py.tpl").read_text(encoding="utf-8")
        route = (self.asset_root / f"{candidate_type}_v1.py.tpl").read_text(encoding="utf-8")
        return common, route

    def _validate_region(self, region: CodeRegion) -> None:
        if region.source_sha256 != hashlib.sha256(region.source.encode("utf-8")).hexdigest():
            raise TemplateRenderError(f"region digest mismatch: {region.name}")
        if "```" in region.source:
            raise TemplateRenderError(f"code fence forbidden in region: {region.name}")
        wrapped = "class _GeneratedRegion:\n" + textwrap.indent(region.source.strip(), "    ")
        try:
            tree = ast.parse(wrapped)
        except SyntaxError as exc:
            raise TemplateRenderError(f"invalid region {region.name}: {exc}") from exc
        class_node = tree.body[0]
        if not isinstance(class_node, ast.ClassDef) or len(class_node.body) != 1:
            raise TemplateRenderError(f"region must contain one method: {region.name}")
        method = class_node.body[0]
        if not isinstance(method, ast.FunctionDef) or method.name != region.name:
            raise TemplateRenderError(f"region method name mismatch: {region.name}")
        if any(isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef)) for node in ast.walk(method)):
            raise TemplateRenderError(f"imports and classes are forbidden in region: {region.name}")

    def _warmup_days(self, spec: StrategySpec) -> int:
        regime_days = spec.execution.regime_lookback_days or 0
        if spec.logic.kind == "traditional":
            return max(spec.logic.lookback_days + 1, regime_days)  # type: ignore[union-attr]
        ml = spec.logic.ml if isinstance(spec.logic, HybridLogic) else spec.logic
        assert isinstance(ml, MLLogic)
        return max(
            ml.training_window_days + 126 + ml.prediction_horizon_days,
            regime_days,
        )

    def _model_import(self, logic: MLLogic | None) -> str:
        if logic is None:
            return ""
        suffix = "Regressor" if logic.task == "relative_alpha_regression" else "Classifier"
        name = (
            f"GradientBoosting{suffix}"
            if logic.model == "gradient_boosting"
            else f"RandomForest{suffix}"
        )
        return f"from sklearn.ensemble import {name}"

    def algorithm_class(self, strategy_id: str) -> str:
        words = re.findall(r"[a-zA-Z0-9]+", strategy_id)
        return "AlphaForge" + "".join(word[:1].upper() + word[1:] for word in words)

    def completion_marker(self, strategy_id: str) -> str:
        normalized = re.sub(r"[^A-Z0-9]+", "_", strategy_id.upper()).strip("_")
        return f"ALPHAFORGE_{normalized}_COMPLETED"


def build_code_region(name: str, source: str) -> CodeRegion:
    normalized = source.strip()
    return CodeRegion(
        name=name,
        source=normalized,
        source_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )
