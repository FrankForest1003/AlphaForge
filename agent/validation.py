from __future__ import annotations

import ast
import hashlib
from typing import Any


# Preflight is intentionally narrow. LEAN and the independent Acceptance Agent own
# runtime and strategy-semantic validation; this layer only blocks syntax errors and
# capabilities that would escape the isolated strategy contract.
FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "httpx",
    "multiprocessing",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "urllib",
}
FORBIDDEN_CALLS = {"__import__", "compile", "eval", "exec", "open"}


def _diagnostic(
    code: str,
    message: str,
    *,
    line: int | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "error",
        "message": message,
        "line": line,
    }


def _call_leaf(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def validate_candidate_source(source_code: str, track: str) -> dict[str, Any]:
    """Run the bounded admission check before submitting source to LEAN.

    ``track`` is retained for API compatibility and trace context. It deliberately
    does not select semantic keyword rules: Traditional/ML/Hybrid integrity is
    evaluated from source plus runtime evidence by the Acceptance Agent.
    """

    del track
    diagnostics: list[dict[str, Any]] = []
    source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        diagnostics.append(
            _diagnostic(
                "PYTHON_SYNTAX",
                f"Python syntax error: {exc.msg}",
                line=exc.lineno,
            )
        )
        return {
            "status": "failed",
            "source_sha256": source_hash,
            "semantic_sha256": None,
            "diagnostics": diagnostics,
        }

    semantic_hash = hashlib.sha256(
        ast.dump(tree, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()
    for node in ast.walk(tree):
        roots: list[str] = []
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots = [(node.module or "").split(".", 1)[0]]
        for root in roots:
            if root in FORBIDDEN_IMPORT_ROOTS:
                diagnostics.append(
                    _diagnostic(
                        "UNSAFE_IMPORT",
                        f"Import '{root}' is not allowed in an Agent strategy.",
                        line=getattr(node, "lineno", None),
                    )
                )
        if isinstance(node, ast.Call) and _call_leaf(node) in FORBIDDEN_CALLS:
            diagnostics.append(
                _diagnostic(
                    "UNSAFE_CALL",
                    f"Call '{_call_leaf(node)}' is not allowed in an Agent strategy.",
                    line=getattr(node, "lineno", None),
                )
            )

    return {
        "status": "failed" if diagnostics else "passed",
        "source_sha256": source_hash,
        "semantic_sha256": semantic_hash,
        "diagnostics": diagnostics,
    }
