"""Compatibility import; canonical implementation lives in strategy_engine."""

from strategy_engine.compiler.renderer import (
    QCTemplateRenderer,
    RenderedTemplate,
    TemplateRenderError,
    build_code_region,
)

__all__ = [
    "QCTemplateRenderer",
    "RenderedTemplate",
    "TemplateRenderError",
    "build_code_region",
]
