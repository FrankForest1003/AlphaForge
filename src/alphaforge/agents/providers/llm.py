from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from alphaforge.agents.providers.structured import StructuredModelClient
from alphaforge.schemas.agent_outputs import (
    CandidateDesign,
    CodeRiskReview,
    CodeRiskReviewRequest,
    DesignRequest,
    GeneratedCode,
    PostBacktestAnalysis,
    PostBacktestAnalysisRequest,
    QCCodeGenerationRequest,
    RepairRequest,
)
from alphaforge.schemas.strategy_spec import StrictModel


class QCCodeDraft(StrictModel):
    source: str = Field(min_length=1)
    used_qc_api: tuple[str, ...]
    assumptions: tuple[str, ...]


class LLMStrategyDesigner:
    def __init__(self, client: StructuredModelClient) -> None:
        self.client = client

    def design(self, request: DesignRequest) -> CandidateDesign:
        return self.client.complete(
            output_model=CandidateDesign,
            system_prompt=(
                "You design one constrained trading strategy candidate. Modify only logic and "
                "explicitly allowed execution fields. Do not return IDs, universe, dates, capital, "
                "resolution, or hard risk-policy changes."
            ),
            payload=request.model_dump(mode="json"),
        )


class LLMQCCodeAgent:
    def __init__(self, client: StructuredModelClient) -> None:
        self.client = client

    def generate(self, request: QCCodeGenerationRequest) -> GeneratedCode:
        draft = self.client.complete(
            output_model=QCCodeDraft,
            system_prompt=(
                "Translate the immutable StrategySpec into QuantConnect/LEAN-compatible Python. "
                "Use only allowed APIs, preserve spec_sha256 exactly, and do not alter strategy semantics."
            ),
            payload=request.model_dump(mode="json"),
        )
        return GeneratedCode(
            strategy_id=request.strategy_spec.strategy_id,
            source=draft.source,
            source_sha256=hashlib.sha256(draft.source.encode("utf-8")).hexdigest(),
            spec_sha256=request.spec_sha256,
            used_qc_api=draft.used_qc_api,
            assumptions=draft.assumptions,
            generator_metadata={
                "agent": "llm_qc_code",
                "template_version": request.template_version,
            },
        )


class LLMCodeRiskAgent:
    def __init__(self, client: StructuredModelClient) -> None:
        self.client = client

    def review(self, request: CodeRiskReviewRequest) -> CodeRiskReview:
        from alphaforge.schemas.agent_outputs import CodeRiskFinding

        class ReviewDraft(StrictModel):
            verdict: Literal["approve", "repair_required", "reject"]
            findings: tuple[CodeRiskFinding, ...]

        draft = self.client.complete(
            output_model=ReviewDraft,
            system_prompt=(
                "Review generated QC code for implementation bugs that can create excessive or "
                "unnecessary risk. Check long/short, leverage, sizing, duplicate orders or schedules, "
                "rebalance and liquidation paths, indicator readiness and warm-up, same-bar or future "
                "data, ML training leakage, weight normalization, unintended exposure, and every "
                "signal/window/fusion parameter against the Spec. Use only the spec, code, static "
                "report, and environment supplied. Do not infer or discuss backtest performance."
            ),
            payload=request.model_dump(mode="json"),
        )
        return CodeRiskReview(
            strategy_id=request.strategy_spec.strategy_id,
            reviewed_source_sha256=request.generated_code.source_sha256,
            spec_sha256=request.generated_code.spec_sha256,
            verdict=draft.verdict,
            findings=draft.findings,
        )


class LLMRepairAgent:
    def __init__(self, client: StructuredModelClient) -> None:
        self.client = client

    def repair(self, request: RepairRequest) -> GeneratedCode:
        draft = self.client.complete(
            output_model=QCCodeDraft,
            system_prompt=(
                "Repair only the implementation defects in the generated QC code. Preserve the "
                "StrategySpec and spec_sha256 exactly."
            ),
            payload=request.model_dump(mode="json"),
        )
        return GeneratedCode(
            strategy_id=request.strategy_spec.strategy_id,
            source=draft.source,
            source_sha256=hashlib.sha256(draft.source.encode("utf-8")).hexdigest(),
            spec_sha256=request.failed_code.spec_sha256,
            used_qc_api=draft.used_qc_api,
            assumptions=draft.assumptions,
            generator_metadata={
                "agent": "llm_repair",
                "repair_attempt": str(request.attempt),
                "failure_source": request.failure_source,
            },
        )


class LLMPostBacktestAnalysisAgent:
    def __init__(self, client: StructuredModelClient) -> None:
        self.client = client

    def analyze(self, request: PostBacktestAnalysisRequest) -> PostBacktestAnalysis:
        return self.client.complete(
            output_model=PostBacktestAnalysis,
            system_prompt=(
                "Analyze all supplied normalized results together. Compare return, drawdown, "
                "volatility, turnover, and fees; cite run IDs; explain trade-offs and provide a "
                "non-binding ranking. Do not make the final hard eligibility decision."
            ),
            payload=request.model_dump(mode="json"),
        )
