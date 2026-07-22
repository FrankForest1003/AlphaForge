from __future__ import annotations

import ast
import hashlib
from typing import Any


EXPECTED_CLASS = "UserStrategy"
EXPECTED_BASE = "AlphaForgeBaseAlgorithm"
EXPECTED_MARKER = "ALPHAFORGE_USER_STRATEGY_COMPLETED"
ALLOWED_IMPORT_ROOTS = {"AlgorithmImports", "alphaforge_base", "datetime"}
FORBIDDEN_IMPORT_ROOTS = {
    "asyncio", "builtins", "ctypes", "ftplib", "http", "importlib", "multiprocessing",
    "os", "pathlib", "pickle", "requests", "shutil", "signal", "socket", "subprocess",
    "sys", "tempfile", "threading", "urllib", "webbrowser",
}
FORBIDDEN_CALLS = {
    "__import__", "breakpoint", "compile", "delattr", "dir", "eval", "exec", "getattr",
    "globals", "help", "input", "locals", "open", "setattr", "type", "vars",
}
REQUIRED_PARAMETERS = {
    "start_date", "end_date", "initial_cash", "symbols", "top_k", "target_gross",
    "max_position_weight", "transaction_cost_bps", "slippage_bps",
}


def code_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}".strip(".")
    return ""


def validate_user_code(code: str) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "Python syntax": False,
        "UserStrategy entry": False,
        "AlphaForge base contract": False,
        "Required strategy hooks": False,
        "Restricted imports and calls": False,
        "ExperimentContract parameters": False,
        "Execution-cost helpers": False,
        "Completion marker": False,
    }
    errors: list[str] = []
    if len(code.encode("utf-8")) > 65_536:
        errors.append("Code exceeds the 64 KiB admission limit.")
        return {"accepted": False, "checks": checks, "errors": errors}
    try:
        tree = ast.parse(code, filename="user_strategy.py")
    except SyntaxError as exc:
        errors.append(f"Python syntax error at line {exc.lineno}: {exc.msg}")
        return {"accepted": False, "checks": checks, "errors": errors}
    checks["Python syntax"] = True

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    entries = [node for node in classes if node.name == EXPECTED_CLASS]
    checks["UserStrategy entry"] = len(entries) == 1
    if len(entries) != 1:
        errors.append("Define exactly one top-level class named UserStrategy.")
        entry = None
    else:
        entry = entries[0]
        bases = {_name(base).split(".")[-1] for base in entry.bases}
        checks["AlphaForge base contract"] = EXPECTED_BASE in bases
        if not checks["AlphaForge base contract"]:
            errors.append("UserStrategy must inherit AlphaForgeBaseAlgorithm.")
        hooks = {
            node.name for node in entry.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        checks["Required strategy hooks"] = {
            "initialize_strategy", "on_alpha_data", "on_alpha_end"
        }.issubset(hooks)
        if not checks["Required strategy hooks"]:
            errors.append(
                "UserStrategy must implement initialize_strategy, on_alpha_data, and on_alpha_end."
            )

    restricted_ok = True
    parameters: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            if not roots.issubset(ALLOWED_IMPORT_ROOTS):
                restricted_ok = False
                errors.append(f"Import is not allowed: {', '.join(sorted(roots))}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_IMPORT_ROOTS or root in FORBIDDEN_IMPORT_ROOTS:
                restricted_ok = False
                errors.append(f"Import is not allowed: {node.module or '(relative import)'}")
        elif isinstance(node, ast.Call):
            call_name = _name(node.func)
            leaf = call_name.split(".")[-1]
            called_names.add(leaf)
            if leaf in FORBIDDEN_CALLS or any(
                part.startswith("__") for part in call_name.split(".") if part
            ):
                restricted_ok = False
                errors.append(f"Call is not allowed: {call_name or leaf}")
            if leaf in {"get_parameter", "_parameter"} and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    parameters.add(argument.value)
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            restricted_ok = False
            errors.append(f"Dunder attribute access is not allowed: {node.attr}")
    checks["Restricted imports and calls"] = restricted_ok

    missing_parameters = sorted(REQUIRED_PARAMETERS.difference(parameters))
    checks["ExperimentContract parameters"] = not missing_parameters
    if missing_parameters:
        errors.append("Missing contract parameters: " + ", ".join(missing_parameters))
    helpers = {"af_configure_security", "af_use_security_benchmark"}
    checks["Execution-cost helpers"] = helpers.issubset(called_names)
    if not checks["Execution-cost helpers"]:
        errors.append("Use af_configure_security and af_use_security_benchmark.")
    checks["Completion marker"] = EXPECTED_MARKER in code
    if not checks["Completion marker"]:
        errors.append(f"on_alpha_end must emit {EXPECTED_MARKER}.")

    errors = list(dict.fromkeys(errors))
    return {"accepted": all(checks.values()), "checks": checks, "errors": errors}
