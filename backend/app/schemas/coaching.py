from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CoachTrackLesson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track: Literal["Traditional", "ML", "Hybrid"]
    evidence_summary: str = Field(min_length=10, max_length=500)
    preserve: list[str] = Field(min_length=1, max_length=3)
    avoid: list[str] = Field(min_length=1, max_length=3)
    next_hypotheses: list[str] = Field(min_length=1, max_length=3)
    next_move: Literal[
        "refine_parameters",
        "rotate_mechanism",
        "rebuild_track",
    ]
    change_scope: Literal[
        "signal",
        "model",
        "portfolio",
        "risk",
        "schedule",
        "multi_component",
    ]
    decision_reason: str = Field(min_length=10, max_length=500)
    parameter_change_budget: int = Field(ge=1, le=4)


class RoundCoachMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_number: int = Field(ge=1, le=5)
    round_summary: str = Field(min_length=10, max_length=700)
    track_lessons: list[CoachTrackLesson] = Field(min_length=3, max_length=3)
    overfitting_guard: str = Field(min_length=10, max_length=500)
