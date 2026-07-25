from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from app.schemas import RoundCoachMemory


COACH_SYSTEM_PROMPT = """You are the AlphaForge Cross-Round AI Coach.
Study only public baselines and AI-generated strategy evidence from the completed
round. Human source code, parameters, results, and score are intentionally absent.
Return one JSON object matching output_shape exactly. Produce one lesson for each of
Traditional, ML, and Hybrid. Use measured evidence, preserve successful mechanisms,
identify failed hypotheses, and choose an explicit next_move for every track.
`computed_track_diagnostics` is authoritative: use `refine_parameters` only when
recent trials show meaningful improvement and the mechanism remains competitive.
Use `rotate_mechanism` when the historical champion was retained, three trials
plateaued, or small parameter changes no longer improve risk-adjusted performance.
Use `rebuild_track` when the whole track remains materially behind its strongest
public reference. Rotation means changing one primary mechanism within the supplied
template DSL while holding most risk controls stable. Rebuild permits a broader but
still auditable hypothesis. Do not write Python or a strategy_spec. Do not claim
future performance. Explicitly guard against multiple-testing overfitting."""


class DeepSeekRoundCoach:
    def __init__(self, **client_options: Any) -> None:
        self.deepseek = DeepSeekJSONClient(**client_options)

    def health(self) -> dict[str, Any]:
        return {
            **self.deepseek.health(),
            "role": "cross_round_ai_coach",
            "information_boundary": "public_baselines_and_ai_only",
        }

    def reflect(
        self,
        *,
        round_number: int,
        evidence: dict[str, Any],
        previous_memory: dict[str, Any] | None,
    ) -> dict[str, Any]:
        shape = {
            "round_number": round_number,
            "round_summary": "Measured summary of the AI field.",
            "track_lessons": [
                {
                    "track": track,
                    "evidence_summary": "What the completed backtests established.",
                    "preserve": ["One evidenced strength."],
                    "avoid": ["One evidenced weakness."],
                    "next_hypotheses": ["One bounded parameter hypothesis."],
                    "next_move": "refine_parameters",
                    "change_scope": (
                        "signal"
                        if track == "Traditional"
                        else "model"
                        if track == "ML"
                        else "multi_component"
                    ),
                    "decision_reason": "Why this degree of change is justified by evidence.",
                    "parameter_change_budget": 2,
                }
                for track in ("Traditional", "ML", "Hybrid")
            ],
            "overfitting_guard": "How the next round should limit historical tuning.",
        }
        completed = self.deepseek.complete_json(
            [
                {"role": "system", "content": COACH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "round_number": round_number,
                            "previous_ai_memory": previous_memory,
                            "ai_and_public_evidence": evidence,
                            "output_shape": shape,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            trace_context={
                "role": "cross_round_ai_coach",
                "round_number": round_number,
                "context_manifest": {
                    "includes": [
                        "public_baselines",
                        "ai_candidates",
                        "ai_critiques",
                        "computed_track_diagnostics",
                    ],
                    "excludes": [
                        "human_source",
                        "human_parameters",
                        "human_results",
                        "human_score",
                    ],
                },
            },
            max_tokens=2_500,
            empty_error="AI Coach returned an empty response",
            invalid_error="AI Coach did not return valid JSON",
            max_attempts=2,
        )
        try:
            memory = RoundCoachMemory.model_validate(completed["payload"])
        except ValidationError as exc:
            raise DeepSeekCallError(str(exc), trace=completed["trace"]) from exc
        tracks = {item.track for item in memory.track_lessons}
        if tracks != {"Traditional", "ML", "Hybrid"}:
            raise DeepSeekCallError(
                "AI Coach must return exactly one lesson per AI track",
                trace=completed["trace"],
            )
        normalized_memory = memory.model_dump(mode="json")
        diagnostics = {
            item.get("track"): item
            for item in evidence.get("computed_track_diagnostics", [])
        }
        for lesson in normalized_memory["track_lessons"]:
            diagnostic = diagnostics.get(lesson["track"])
            if not diagnostic:
                continue
            lesson["next_move"] = diagnostic["recommended_next_move"]
            lesson["change_scope"] = diagnostic[
                "recommended_change_scope"
            ]
            lesson["parameter_change_budget"] = diagnostic[
                "recommended_parameter_change_budget"
            ]
        return {
            "memory": normalized_memory,
            "usage": completed["usage"],
            "trace": completed["trace"],
        }
