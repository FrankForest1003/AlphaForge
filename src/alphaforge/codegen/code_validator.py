"""Compatibility import; canonical implementation lives in strategy_engine."""

from strategy_engine.validators.code import (
    DEFAULT_ALLOWED_IMPORTS,
    DEFAULT_ALLOWED_QC_API,
    validate_generated_code,
)

__all__ = [
    "DEFAULT_ALLOWED_IMPORTS",
    "DEFAULT_ALLOWED_QC_API",
    "validate_generated_code",
]
