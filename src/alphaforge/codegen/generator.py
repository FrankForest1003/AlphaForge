from __future__ import annotations

import hashlib
import json

from alphaforge.schemas.agent_outputs import GeneratedCode, RepairRequest
from alphaforge.schemas.strategy_spec import StrategySpec
from alphaforge.strategy_spec.versioning import strategy_spec_digest


class DeterministicCodeGenerator:
    """Auditable placeholder for the later LEAN template/code-generation provider."""

    def generate(self, spec: StrategySpec) -> GeneratedCode:
        payload = json.dumps(spec.model_dump(mode="json"), sort_keys=True, indent=2)
        source = (
            '"""Generated mock artefact; not production LEAN code."""\n\n'
            "import json\n\n"
            f"STRATEGY_SPEC = json.loads({payload!r})\n\n"
            "def describe() -> str:\n"
            "    return f\"{STRATEGY_SPEC['strategy_id']}:{STRATEGY_SPEC['candidate_type']}\"\n"
        )
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return GeneratedCode(
            strategy_id=spec.strategy_id,
            generator="deterministic-mock-v1",
            source=source,
            sha256=digest,
            spec_sha256=strategy_spec_digest(spec),
        )


class DeterministicRepairProvider:
    """Mock repair: regenerate from the same immutable spec, never edit semantics."""

    def __init__(self) -> None:
        self.generator = DeterministicCodeGenerator()

    def repair(self, request: RepairRequest) -> GeneratedCode:
        return self.generator.generate(request.spec)
