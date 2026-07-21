from __future__ import annotations

import ast
import hashlib
import re

from alphaforge.schemas.agent_outputs import CodeValidationResult, GeneratedCode
from alphaforge.schemas.strategy_spec import StrategySpec
from alphaforge.strategy_spec.versioning import strategy_spec_digest

DEFAULT_ALLOWED_QC_API = (
    "QCAlgorithm",
    "SetStartDate",
    "SetEndDate",
    "SetCash",
    "AddEquity",
    "History",
    "SetHoldings",
    "Liquidate",
    "Schedule",
    "Schedule.On",
    "DateRules",
    "DateRules.MonthStart",
    "TimeRules",
    "TimeRules.AfterMarketOpen",
    "Time.date",
    "Resolution.Daily",
    "SetWarmUp",
)

DEFAULT_ALLOWED_IMPORTS = ("AlgorithmImports", "numpy", "pandas", "sklearn")

_FORBIDDEN_IMPORTS = {"os", "subprocess", "socket", "requests", "urllib", "pathlib"}
_FORBIDDEN_PATTERNS = {
    r"\bopen\s*\(": "FORBIDDEN_FILE_ACCESS",
    r"\beval\s*\(": "FORBIDDEN_EVAL",
    r"\bexec\s*\(": "FORBIDDEN_EXEC",
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

    tree: ast.AST | None = None
    try:
        tree = ast.parse(code.source)
    except SyntaxError as exc:
        errors.append(f"PYTHON_SYNTAX_ERROR:{exc.lineno}:{exc.offset}")

    observed: set[str] = set()
    if tree is not None:
        has_qc_class = False
        has_initialize = False
        has_rebalance = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name.split(".")[0] for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [(node.module or "").split(".")[0]]
                )
                forbidden = sorted(name for name in names if name in _FORBIDDEN_IMPORTS)
                if forbidden:
                    errors.append("FORBIDDEN_IMPORT:" + ",".join(forbidden))
                imported_roots = {(node.module or "").split(".")[0]} if isinstance(node, ast.ImportFrom) else {
                    alias.name.split(".")[0] for alias in node.names
                }
                disallowed = sorted(imported_roots - set(allowed_imports))
                if disallowed:
                    errors.append("IMPORT_NOT_ALLOWED:" + ",".join(disallowed))
            if isinstance(node, ast.ClassDef):
                bases = {base.id for base in node.bases if isinstance(base, ast.Name)}
                if "QCAlgorithm" in bases:
                    has_qc_class = True
                    observed.add("QCAlgorithm")
                    has_initialize = any(
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == "Initialize"
                        for child in node.body
                    )
                    has_rebalance = any(
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == "Rebalance"
                        for child in node.body
                    )
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    path = _attribute_path(node.func)
                    if path is not None:
                        normalized = path.removeprefix("self.")
                        root = normalized.split(".", 1)[0]
                        if path.startswith("self.") and root[:1].isupper():
                            observed.add(normalized)
                        elif root in {"Resolution", "DateRules", "TimeRules"}:
                            observed.add(normalized)
                    else:
                        observed.add(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    if node.func.id == "QCAlgorithm":
                        observed.add(node.func.id)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"Resolution", "DateRules", "TimeRules"}
            ):
                observed.add(f"{node.value.id}.{node.attr}")
        if not has_qc_class:
            errors.append("MISSING_QCALGORITHM_CLASS")
        if not has_initialize:
            errors.append("MISSING_INITIALIZE_METHOD")
        if not has_rebalance:
            errors.append("MISSING_REBALANCE_METHOD")
        for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
            for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
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

    observed_not_allowed = sorted(
        api
        for api in observed
        if (
            api.split(".", 1)[0] in {"Resolution", "DateRules", "TimeRules"}
            or api.split(".", 1)[0][:1].isupper()
        )
        and api not in allowed_qc_api
    )
    if observed_not_allowed:
        errors.append("QC_API_NOT_ALLOWED_OBSERVED:" + ",".join(observed_not_allowed))

    missing_declarations = sorted(
        api for api in code.used_qc_api if api not in observed and api != "Schedule"
    )
    if missing_declarations:
        warnings.append("DECLARED_QC_API_NOT_OBSERVED:" + ",".join(missing_declarations))
    return CodeValidationResult(
        valid=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        observed_qc_api=tuple(sorted(observed & set(allowed_qc_api))),
    )
