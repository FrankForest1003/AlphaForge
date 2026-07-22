from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BaselineRunView(BaseModel):
    strategy_id: str
    display_name: str
    family: str
    worker_run_id: str | None = None
    state: str
    eligible_for_comparison: bool = False
    result_hash: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BaselineBatchView(BaseModel):
    batch_id: str
    battle_id: str
    state: str
    contract_hash: str
    created_at: str
    updated_at: str
    runs: list[BaselineRunView]
    error: str | None = None
