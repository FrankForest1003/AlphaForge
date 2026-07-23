from __future__ import annotations

import ast
import hashlib
import re
from typing import Any


ALLOWED_IMPORT_ROOTS = {
    "AlgorithmImports",
    "alphaforge_base",
    "collections",
    "datetime",
    "math",
    "numpy",
    "pandas",
    "sklearn",
    "statistics",
}

FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "httpx",
    "importlib",
    "multiprocessing",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}

FORBIDDEN_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "open",
}

REQUIRED_PARAMETER_NAMES = {
    "symbols",
    "start_date",
    "end_date",
    "initial_cash",
    "benchmark",
    "transaction_cost_bps",
    "slippage_bps",
}

RESERVED_BASE_METHODS = {
    "initialize",
    "af_configure_security",
    "af_liquidate_all",
    "af_rebalance_to_weights",
    "af_record_ml_prediction",
    "af_record_ml_training",
    "af_record_signal",
    "af_track_symbol",
    "af_use_security_benchmark",
}


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: str = "error",
    line: int | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "line": line,
    }


def _call_name(node: ast.Call) -> str:
    value = node.func
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        parts = [value.attr]
        current = value.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _literal_dict_keys(node: ast.AST) -> set[str] | None:
    if not isinstance(node, ast.Dict):
        return None
    keys: set[str] = set()
    for key in node.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.add(key.value)
    return keys


def _is_zero(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and node.value == 0
    )


def _depends_on_negative_index(node: ast.AST, negative_names: set[str]) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return True
    if isinstance(node, ast.Name):
        return node.id in negative_names
    if isinstance(node, ast.BinOp):
        if _depends_on_negative_index(node.left, negative_names):
            return True
        if isinstance(node.op, ast.Add):
            return _depends_on_negative_index(node.right, negative_names)
    return False


def _name_is_iloc_index(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "iloc"
        ):
            continue
        if any(
            isinstance(part, ast.Name) and part.id == name
            for part in ast.walk(node.slice)
        ):
            return True
    return False


def validate_candidate_source(source_code: str, track: str) -> dict[str, Any]:
    """Deterministically reject common unsafe or non-runnable Agent output."""

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

    imported_roots: set[str] = set()
    user_strategy: ast.ClassDef | None = None
    call_names: list[tuple[str, int | None]] = []
    calls: list[ast.Call] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            imported_roots.add((node.module or "").split(".", 1)[0])
        elif isinstance(node, ast.ClassDef) and node.name == "UserStrategy":
            user_strategy = node
        elif isinstance(node, ast.Call):
            calls.append(node)
            call_names.append((_call_name(node), getattr(node, "lineno", None)))
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr.lower() == "history"
        ):
            diagnostics.append(
                _diagnostic(
                    "LEAN_HISTORY_SUBSCRIPT",
                    "Do not use self.history[TradeBar](...) as a pandas DataFrame; "
                    "use self.history(...) and af_split_history_frames.",
                    line=getattr(node, "lineno", None),
                )
            )

    for root in sorted(imported_roots):
        if root in FORBIDDEN_IMPORT_ROOTS:
            diagnostics.append(
                _diagnostic(
                    "UNSAFE_IMPORT",
                    f"Import '{root}' is not allowed in an Agent strategy.",
                )
            )
        elif root and root not in ALLOWED_IMPORT_ROOTS:
            diagnostics.append(
                _diagnostic(
                    "UNSUPPORTED_IMPORT",
                    f"Import '{root}' is outside the deterministic Agent capability set.",
                )
            )

    for name, line in call_names:
        leaf = name.rsplit(".", 1)[-1]
        if leaf in FORBIDDEN_CALLS:
            diagnostics.append(
                _diagnostic(
                    "UNSAFE_CALL",
                    f"Call '{name}' is not allowed in an Agent strategy.",
                    line=line,
                )
            )

    for call in calls:
        name = _call_name(call)
        if name.endswith("schedule.on"):
            valid_arity = len(call.args) in {3, 4} and not call.keywords
            valid_name = (
                len(call.args) != 4
                or (
                    isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                )
            )
            callback = call.args[-1] if call.args else None
            valid_callback = isinstance(
                callback,
                (ast.Attribute, ast.Name, ast.Lambda),
            )
            if not (valid_arity and valid_name and valid_callback):
                diagnostics.append(
                    _diagnostic(
                        "LEAN_SCHEDULE_SIGNATURE",
                        "Use schedule.on(date_rule, time_rule, callback) or "
                        "schedule.on(name, date_rule, time_rule, callback); "
                        "LEAN Python has no two-argument schedule builder.",
                        line=getattr(call, "lineno", None),
                    )
                )
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "do"
            and isinstance(call.func.value, ast.Call)
            and _call_name(call.func.value).endswith("schedule.on")
        ):
            diagnostics.append(
                _diagnostic(
                    "LEAN_SCHEDULE_BUILDER",
                    "Do not chain .do(...) after schedule.on; pass the callback "
                    "directly to schedule.on.",
                    line=getattr(call, "lineno", None),
                )
            )

    evidence_specs = {
        "af_record_ml_training": {
            "model_type",
            "training_rows",
            "label_horizon_days",
            "random_seed",
            "feature_names",
        },
        "af_record_ml_prediction": {
            "symbol",
            "predicted_alpha",
            "rank",
            "selected",
        },
    }
    for call in calls:
        leaf = _call_name(call).rsplit(".", 1)[-1]
        if leaf not in evidence_specs:
            continue
        if len(call.args) != 1 or call.keywords:
            diagnostics.append(
                _diagnostic(
                    "ALPHAFORGE_EVIDENCE_SIGNATURE",
                    f"{leaf} accepts exactly one positional dict payload and "
                    "no keyword arguments.",
                    line=getattr(call, "lineno", None),
                )
            )
            continue
        keys = _literal_dict_keys(call.args[0])
        if keys is None:
            diagnostics.append(
                _diagnostic(
                    "ALPHAFORGE_EVIDENCE_PAYLOAD",
                    f"{leaf} must receive a literal dict so its evidence schema "
                    "can be checked before LEAN execution.",
                    line=getattr(call, "lineno", None),
                )
            )
            continue
        missing = sorted(evidence_specs[leaf] - keys)
        if missing:
            diagnostics.append(
                _diagnostic(
                    "ALPHAFORGE_EVIDENCE_KEYS",
                    f"{leaf} payload is missing: {', '.join(missing)}.",
                    line=getattr(call, "lineno", None),
                )
            )

    for call in calls:
        if _call_name(call).rsplit(".", 1)[-1] != "af_record_signal":
            continue
        if (
            len(call.args) != 2
            or call.keywords
            or _literal_dict_keys(call.args[1]) is None
        ):
            diagnostics.append(
                _diagnostic(
                    "ALPHAFORGE_SIGNAL_SIGNATURE",
                    "af_record_signal accepts exactly (name, one literal dict payload).",
                    line=getattr(call, "lineno", None),
                )
            )

    negative_index_names: set[str] = set()
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            value = assignment.value
            if not _depends_on_negative_index(value, negative_index_names):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in negative_index_names:
                    negative_index_names.add(target.id)
                    changed = True
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], (ast.Lt, ast.LtE))
            and len(node.test.comparators) == 1
            and _is_zero(node.test.comparators[0])
        ):
            continue
        name = node.test.left.id
        exits_branch = any(
            isinstance(part, (ast.Continue, ast.Return))
            for statement in node.body
            for part in ast.walk(statement)
        )
        if (
            name in negative_index_names
            and exits_branch
            and _name_is_iloc_index(tree, name)
        ):
            diagnostics.append(
                _diagnostic(
                    "IMPOSSIBLE_ILOC_GUARD",
                    f"'{name}' is intentionally a negative trailing iloc index; "
                    "rejecting it for being below zero makes the signal path unreachable. "
                    "Use a row-count check instead.",
                    line=getattr(node, "lineno", None),
                )
            )

    for call in calls:
        if _call_name(call).rsplit(".", 1)[-1] != "fillna":
            continue
        receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
        if not (
            call.args
            and _is_zero(call.args[0])
            and isinstance(receiver, ast.Call)
            and _call_name(receiver).rsplit(".", 1)[-1] == "shift"
            and receiver.args
            and isinstance(receiver.args[0], ast.UnaryOp)
            and isinstance(receiver.args[0].op, ast.USub)
        ):
            continue
        diagnostics.append(
            _diagnostic(
                "ML_FORWARD_LABEL_FILL",
                "Do not fill unavailable forward labels with zero after a negative "
                "shift; drop the final label-horizon rows before fitting.",
                line=getattr(call, "lineno", None),
            )
        )

    if user_strategy is None:
        diagnostics.append(
            _diagnostic(
                "MISSING_ENTRY_CLASS",
                "The complete file must define class UserStrategy.",
            )
        )
    else:
        base_names = {
            base.id
            for base in user_strategy.bases
            if isinstance(base, ast.Name)
        }
        if "AlphaForgeBaseAlgorithm" not in base_names:
            diagnostics.append(
                _diagnostic(
                    "INVALID_ENTRY_BASE",
                    "UserStrategy must inherit AlphaForgeBaseAlgorithm.",
                    line=user_strategy.lineno,
                )
            )
        method_names = {
            node.name
            for node in user_strategy.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if "initialize_strategy" not in method_names:
            diagnostics.append(
                _diagnostic(
                    "MISSING_INITIALIZER",
                    "UserStrategy must implement initialize_strategy.",
                    line=user_strategy.lineno,
                )
            )
        overridden = sorted(method_names.intersection(RESERVED_BASE_METHODS))
        if overridden:
            diagnostics.append(
                _diagnostic(
                    "ALPHAFORGE_BASE_OVERRIDE",
                    "Do not redefine AlphaForge base-owned methods: "
                    + ", ".join(overridden),
                    line=user_strategy.lineno,
                )
            )

    consumed_parameters = {
        str(call.args[0].value)
        for call in calls
        if _call_name(call).rsplit(".", 1)[-1] in {"_parameter", "get_parameter"}
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }
    missing_parameters = sorted(REQUIRED_PARAMETER_NAMES - consumed_parameters)
    if missing_parameters:
        diagnostics.append(
            _diagnostic(
                "MISSING_RUN_SETTINGS",
                "The strategy must consume every shared run setting; missing: "
                + ", ".join(missing_parameters),
            )
        )

    required_fragments = {
        "af_configure_security": "Configure fees and slippage with af_configure_security.",
        "af_track_symbol": "Track every candidate Symbol with af_track_symbol.",
        "af_rebalance_to_weights": (
            "Use af_rebalance_to_weights for the long-only Daily portfolio."
        ),
    }
    for fragment, message in required_fragments.items():
        if fragment not in source_code:
            diagnostics.append(
                _diagnostic("MISSING_ALPHAFORGE_API", message)
            )

    for pattern, message in (
        (
            r"\bself\.set_holdings\s*\(",
            "Use af_rebalance_to_weights instead of direct set_holdings.",
        ),
        (
            r"\bself\.liquidate\s*\(",
            "Use af_rebalance_to_weights or af_liquidate_all instead of direct liquidate.",
        ),
        (
            r"\b(?:xgb\.)?DMatrix\s*\(",
            "Low-level XGBoost DMatrix is excluded from the stable Agent capability set.",
        ),
        (
            r"\.object_store\b|\bObjectStore\b",
            "Object Store persistence is unnecessary for one deterministic backtest.",
        ),
    ):
        match = re.search(pattern, source_code)
        if match:
            diagnostics.append(
                _diagnostic(
                    "UNSTABLE_LEAN_PATTERN",
                    message,
                    line=source_code.count("\n", 0, match.start()) + 1,
                )
            )

    uses_fit = any(name.endswith(".fit") for name, _ in call_names)
    uses_predict = any(name.endswith(".predict") for name, _ in call_names)
    ml_track = track in {"ML", "Hybrid"}
    if ml_track:
        if not uses_fit or not uses_predict:
            diagnostics.append(
                _diagnostic(
                    "MISSING_ML_FLOW",
                    f"{track} must fit a model and consume model predictions.",
                )
            )
        for fragment, message in (
            (
                "af_record_ml_training",
                "Record fitted-model evidence with af_record_ml_training.",
            ),
            (
                "af_record_ml_prediction",
                "Record prediction-to-selection evidence with af_record_ml_prediction.",
            ),
        ):
            if fragment not in source_code:
                diagnostics.append(
                    _diagnostic("MISSING_RUNTIME_EVIDENCE", message)
                )
    elif uses_fit or uses_predict or imported_roots.intersection(
        {"sklearn", "xgboost", "lightgbm"}
    ):
        diagnostics.append(
            _diagnostic(
                "TRACK_MISMATCH",
                "Traditional candidates must not fit or invoke a machine-learning model.",
            )
        )

    if track in {"Traditional", "Hybrid"} and "af_record_signal" not in source_code:
        diagnostics.append(
            _diagnostic(
                "MISSING_RUNTIME_EVIDENCE",
                f"{track} must record its transparent signal with af_record_signal.",
            )
        )

    if track == "Hybrid":
        transparent_signal_terms = (
            "momentum",
            "mean_reversion",
            "relative_strength",
            "trend",
            "volatility",
        )
        if not any(term in source_code.lower() for term in transparent_signal_terms):
            diagnostics.append(
                _diagnostic(
                    "MISSING_HYBRID_SIGNAL",
                    "Hybrid must combine predictions with a named transparent market signal.",
                )
            )

    warnings: list[dict[str, Any]] = []
    if "self.is_warming_up" not in source_code:
        warnings.append(
            _diagnostic(
                "NO_WARMUP_GUARD",
                "Add an is_warming_up guard before training or trading.",
                severity="warning",
            )
        )

    return {
        "status": "failed" if diagnostics else "passed",
        "source_sha256": source_hash,
        "semantic_sha256": semantic_hash,
        "diagnostics": diagnostics,
        "warnings": warnings,
        "consumed_run_settings": sorted(consumed_parameters),
        "contract_version": "agent-source-v3",
    }
