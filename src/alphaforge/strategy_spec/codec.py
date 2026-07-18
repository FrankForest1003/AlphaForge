from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from alphaforge.schemas.strategy_spec import StrategySpec


class StrategyDocumentCodec(Protocol):
    """Anti-corruption layer for the future team DSL."""

    media_type: str

    def decode(self, document: Mapping[str, Any]) -> StrategySpec: ...

    def encode(self, spec: StrategySpec) -> dict[str, Any]: ...


class CanonicalJsonCodec:
    """Temporary identity codec used until the external DSL is frozen."""

    media_type = "application/vnd.alphaforge.strategy+json;version=0.1-draft"

    def decode(self, document: Mapping[str, Any]) -> StrategySpec:
        return StrategySpec.model_validate(document)

    def encode(self, spec: StrategySpec) -> dict[str, Any]:
        return spec.model_dump(mode="json")
