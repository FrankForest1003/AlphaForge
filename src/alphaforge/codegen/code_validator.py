from __future__ import annotations

import ast
import hashlib

from alphaforge.schemas.agent_outputs import CodeValidationResult, GeneratedCode
from alphaforge.schemas.strategy_spec import StrategySpec
from alphaforge.strategy_spec.versioning import strategy_spec_digest


def validate_generated_code(
    spec: StrategySpec,
    code: GeneratedCode,
) -> CodeValidationResult:
    errors: list[str] = []
    if code.strategy_id != spec.strategy_id:
        errors.append("STRATEGY_ID_MISMATCH")
    if code.spec_sha256 != strategy_spec_digest(spec):
        errors.append("SEMANTIC_DIGEST_MISMATCH")
    if code.sha256 != hashlib.sha256(code.source.encode("utf-8")).hexdigest():
        errors.append("SOURCE_DIGEST_MISMATCH")
    try:
        ast.parse(code.source)
    except SyntaxError as exc:
        errors.append(f"PYTHON_SYNTAX_ERROR:{exc.lineno}:{exc.offset}")
    return CodeValidationResult(valid=not errors, errors=tuple(errors))
