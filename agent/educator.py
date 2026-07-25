from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent.client import DeepSeekCallError, DeepSeekJSONClient
from app.schemas.education import EducationReview


EDUCATOR_SYSTEM_PROMPT = """You are AlphaForge's Teaching Explainer.
You do not select winners, change scores, generate Python, or claim future returns.
Explain only the deterministic evidence in the supplied JSON.

Return exactly one JSON object matching output_shape. Every numerical claim must
be supported by evidence. Distinguish a backtest observation from a hypothesis.
For each next-round action, change one valid strategy_spec parameter only. Copy
its current value from champion_strategy_spec and propose a value within the
provided parameter_bounds. Suggestions must be falsifiable and mention a trade-off.
Do not recommend optimizing several parameters at once. If robustness evidence is
absent, say that robustness is unknown instead of assuming it.
"""


OUTPUT_SHAPE = {
    "strategy_explanation": {
        "thesis": "plain-language explanation",
        "mechanics": ["3-6 steps from signal to portfolio"],
        "why_it_led": ["2-5 evidence-grounded reasons"],
        "failure_modes": ["2-5 concrete limitations"],
    },
    "next_round_actions": [
        {
            "title": "short experiment name",
            "hypothesis": "one-variable hypothesis",
            "parameter_path": "strategy_spec dot path",
            "current_value": "exact current value as text",
            "proposed_value": "one value or narrow range as text",
            "expected_metric": "CAGR | Sharpe Ratio | Maximum Drawdown | Turnover | Robustness",
            "tradeoff": "what may become worse",
            "validation": "how to judge the next backtest",
        }
    ],
    "quant_concept": {
        "title": "concept selected for this run",
        "explanation": "grounded lesson",
        "chart_hint": "risk_return | drawdown_path | turnover_cost | iteration_stability | diversification",
        "takeaway": "one practical takeaway",
    },
    "overfitting_watch": ["2-4 warnings tied to this run"],
}


class DeepSeekEducator:
    def __init__(self, **client_options: Any) -> None:
        self.deepseek = DeepSeekJSONClient(**client_options)

    def health(self) -> dict[str, Any]:
        return {
            **self.deepseek.health(),
            "output_mode": "grounded_education_only",
            "prompt_contract_version": "teaching-explainer-v1",
        }

    def explain(self, *, evidence: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": EDUCATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Explain this completed Forge round to a finance student.",
                        "evidence": evidence,
                        "parameter_bounds": {
                            "selection.top_k": "2-10",
                            "selection.require_positive_score": "true or false",
                            "portfolio.gross_exposure": "0.50-0.98",
                            "portfolio.max_position_weight": "0.10-0.60",
                            "portfolio.volatility_window": "10-252",
                            "portfolio.rebalance_threshold": "0.00-0.10",
                            "schedule.frequency": "weekly or monthly",
                            "risk.market_trend_filter": "true or false",
                            "risk.market_sma_window": "20-252",
                        },
                        "output_shape": OUTPUT_SHAPE,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]
        last_call: dict[str, Any] | None = None
        last_error: ValidationError | None = None
        for semantic_attempt in range(2):
            call = self.deepseek.complete_json(
                messages,
                trace_context={
                    "stage": "education",
                    "run_id": evidence.get("run_id"),
                    "semantic_attempt": semantic_attempt + 1,
                },
                max_tokens=2200,
                empty_error="Teaching Explainer returned no content",
                invalid_error="Teaching Explainer did not return valid JSON",
                max_attempts=1,
            )
            last_call = call
            try:
                review = EducationReview.model_validate(call["payload"])
            except ValidationError as exc:
                last_error = exc
                if semantic_attempt == 0:
                    messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "Your prior JSON did not match output_shape. Return "
                                "a corrected complete object only. Validation error: "
                                + str(exc)[:1200]
                            ),
                        },
                    ]
                    continue
                break
            return {
                "review": review.model_dump(mode="json"),
                "usage": call["usage"],
                "trace": call["trace"],
            }
        assert last_call is not None and last_error is not None
        raise DeepSeekCallError(
            f"Teaching Explainer schema validation failed: {last_error}",
            trace=last_call["trace"],
        ) from last_error
