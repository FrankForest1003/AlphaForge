from __future__ import annotations

import ast
import hashlib
import re

from alphaforge.schemas.agent_outputs import CodeValidationResult, GeneratedCode
from alphaforge.schemas.strategy_spec import StrategySpec
from alphaforge.strategy_spec.versioning import strategy_spec_digest

DEFAULT_ALLOWED_QC_API = (
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

DEFAULT_ALLOWED_IMPORTS = (
    "AlgorithmImports",
    "alphaforge_base",
    "datetime",
    "numpy",
    "pandas",
    "sklearn",
)

_FORBIDDEN_IMPORTS = {
    "os",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "pathlib",
    "yfinance",
}
_FORBIDDEN_PATTERNS = {
    r"\bopen\s*\(": "FORBIDDEN_FILE_ACCESS",
    r"\beval\s*\(": "FORBIDDEN_EVAL",
    r"\bexec\s*\(": "FORBIDDEN_EXEC",
    r"\bhistory\.loc\s*\[": "UNSAFE_HISTORY_LOC_ACCESS",
    r"Resolution\.(?:HOUR|MINUTE|Hour|Minute)": "FORBIDDEN_DATA_RESOLUTION",
    r"DataNormalizationMode\.(?:ADJUSTED|Adjusted)": "WRONG_NORMALIZATION_MODE",
}


def _attribute_path(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def validate_generated_code(
    spec: StrategySpec,
    code: GeneratedCode,
    *,
    allowed_qc_api: tuple[str, ...] = DEFAULT_ALLOWED_QC_API,
    allowed_imports: tuple[str, ...] = DEFAULT_ALLOWED_IMPORTS,
) -> CodeValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if code.strategy_id != spec.strategy_id:
        errors.append("STRATEGY_ID_MISMATCH")
    if code.spec_sha256 != strategy_spec_digest(spec):
        errors.append("SEMANTIC_DIGEST_MISMATCH")
    if code.source_sha256 != hashlib.sha256(code.source.encode("utf-8")).hexdigest():
        errors.append("SOURCE_DIGEST_MISMATCH")
    undeclared = sorted(set(code.used_qc_api) - set(allowed_qc_api))
    if undeclared:
        errors.append("QC_API_NOT_ALLOWED:" + ",".join(undeclared))

    tree: ast.Module | None = None
    try:
        tree = ast.parse(code.source)
    except SyntaxError as exc:
        errors.append(f"PYTHON_SYNTAX_ERROR:{exc.lineno}:{exc.offset}")

    observed: set[str] = set()
    if tree is not None:
        strategy_classes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and any(
                isinstance(base, ast.Name) and base.id == "AlphaForgeBaseAlgorithm"
                for base in node.bases
            )
        ]
        class_methods: set[str] = set()
        if len(strategy_classes) != 1:
            errors.append("REQUIRES_ONE_ALPHAFORGE_BASE_CLASS")
        else:
            class_methods = {
                child.name
                for child in strategy_classes[0].body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for required in ("initialize_strategy", "rebalance", "on_alpha_end"):
                if required not in class_methods:
                    errors.append(f"MISSING_{required.upper()}_METHOD")

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                roots = (
                    {alias.name.split(".")[0] for alias in node.names}
                    if isinstance(node, ast.Import)
                    else {(node.module or "").split(".")[0]}
                )
                forbidden = sorted(roots & _FORBIDDEN_IMPORTS)
                if forbidden:
                    errors.append("FORBIDDEN_IMPORT:" + ",".join(forbidden))
                disallowed = sorted(roots - set(allowed_imports))
                if disallowed:
                    errors.append("IMPORT_NOT_ALLOWED:" + ",".join(disallowed))

            if isinstance(node, ast.Call):
                path = _attribute_path(node.func)
                if path:
                    normalized = path.removeprefix("self.")
                    if normalized in allowed_qc_api:
                        observed.add(normalized)
                    if (
                        path.startswith("self.")
                        and "." not in normalized
                        and normalized not in allowed_qc_api
                        and normalized not in class_methods
                        and not normalized.startswith("_")
                    ):
                        errors.append(f"QC_API_NOT_ALLOWED_OBSERVED:{normalized}")
                    if normalized in {"set_holdings", "liquidate"}:
                        errors.append("DIRECT_ORDER_API_BYPASSES_STAGED_REBALANCE")

            if isinstance(node, ast.ExceptHandler):
                if node.type is None and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    errors.append("FORBIDDEN_BARE_EXCEPT_PASS")

        for function in (
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ):
            for call in (
                node for node in ast.walk(function) if isinstance(node, ast.Call)
            ):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "shift"
                    and call.args
                    and isinstance(call.args[0], ast.UnaryOp)
                    and isinstance(call.args[0].op, ast.USub)
                ):
                    continue
                if function.name != "build_training_set":
                    errors.append("POTENTIAL_LOOKAHEAD_SHIFT")

    for pattern, code_name in _FORBIDDEN_PATTERNS.items():
        if re.search(pattern, code.source):
            errors.append(code_name)

    required_source_markers = {
        "DataNormalizationMode.RAW": "RAW_NORMALIZATION_NOT_ENFORCED",
        f"self.target_gross = {spec.execution.target_gross!r}": "TARGET_GROSS_SPEC_MISMATCH",
        "self.settings.free_portfolio_value_percentage = 0.02": "CASH_RESERVE_NOT_CONFIGURED",
        "self.af_rebalance_to_weights(": "STAGED_REBALANCE_NOT_USED",
        "_COMPLETED\")": "COMPLETION_MARKER_MISSING",
    }
    for marker, error in required_source_markers.items():
        if marker not in code.source:
            errors.append(error)

    missing_declarations = sorted(
        api for api in code.used_qc_api if api not in observed and "." not in api
    )
    if missing_declarations:
        warnings.append("DECLARED_QC_API_NOT_OBSERVED:" + ",".join(missing_declarations))
    return CodeValidationResult(
        valid=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        observed_qc_api=tuple(sorted(observed)),
    )
