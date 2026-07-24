from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.schemas.strategy_template import StrategyTemplateSpec


TEMPLATE_VERSION = "template-v1"
TEMPLATE_MARKER = "__ALPHAFORGE_STRATEGY_SPEC_JSON__"
TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "parameterized_strategy.py.tmpl"
)


def validate_strategy_spec(
    payload: StrategyTemplateSpec | dict[str, Any],
) -> StrategyTemplateSpec:
    if isinstance(payload, StrategyTemplateSpec):
        return payload
    return StrategyTemplateSpec.model_validate(payload)


def compile_strategy_source(
    payload: StrategyTemplateSpec | dict[str, Any],
) -> str:
    """Inject one validated JSON specification into the immutable LEAN template."""

    spec = validate_strategy_spec(payload)
    canonical_json = json.dumps(
        spec.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if template.count(TEMPLATE_MARKER) != 1:
        raise RuntimeError("strategy template must contain exactly one spec marker")
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    source = template.replace(TEMPLATE_MARKER, repr(canonical_json))
    return source.replace("__ALPHAFORGE_STRATEGY_SPEC_SHA256__", digest)


def strategy_spec_json_schema() -> dict[str, Any]:
    """Compact machine-readable contract for the future parameter-only Agent."""

    return StrategyTemplateSpec.model_json_schema()

