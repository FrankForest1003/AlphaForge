from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from alphaforge.schemas.agent_outputs import BuiltCandidate, CandidateDesign
from alphaforge.schemas.strategy_spec import StrategySpec


def _json_diff(before: Any, after: Any, path: str = "") -> list[str]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{key}"
            if key not in before or key not in after:
                changes.append(child)
            else:
                changes.extend(_json_diff(before[key], after[key], child))
        return changes
    if before != after:
        return [path or "/"]
    return []


class SpecBuilder:
    def build(
        self,
        *,
        optimization_id: str,
        parent_spec: StrategySpec,
        design: CandidateDesign,
        round_number: int = 1,
    ) -> BuiltCandidate:
        execution = parent_spec.execution
        execution_updates = {
            field: value
            for field, value in design.execution_changes.model_dump().items()
            if value is not None
        }
        if execution_updates:
            execution = execution.model_copy(update=execution_updates)

        candidate = StrategySpec.model_validate(
            parent_spec.model_copy(
                update={
                    "strategy_id": f"{optimization_id}_{design.candidate_type}_r{round_number}",
                    "parent_strategy_id": parent_spec.strategy_id,
                    "candidate_type": design.candidate_type,
                    "execution": execution,
                    "logic": design.logic,
                }
            ).model_dump()
        )
        changed_paths = tuple(
            _json_diff(
                parent_spec.model_dump(mode="json"),
                candidate.model_dump(mode="json"),
            )
        )
        return BuiltCandidate(design=design, spec=candidate, changed_paths=changed_paths)
