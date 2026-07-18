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
