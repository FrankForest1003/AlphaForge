from __future__ import annotations

import hashlib
import json

from alphaforge.schemas.strategy_spec import StrategySpec


def strategy_spec_digest(spec: StrategySpec) -> str:
    payload = json.dumps(
        spec.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def strategy_semantic_digest(spec: StrategySpec) -> str:
    """Digest executable semantics while ignoring identity and lineage fields."""
    payload = spec.model_dump(mode="json")
    payload.pop("strategy_id", None)
    payload.pop("parent_strategy_id", None)
    payload.pop("candidate_type", None)
    # This is a post-backtest admission threshold, not executable strategy logic.
    payload["risk"].pop("max_drawdown_limit", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
