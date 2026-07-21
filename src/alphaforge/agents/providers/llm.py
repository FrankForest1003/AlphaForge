from __future__ import annotations

from typing import Literal

from alphaforge.agents.context import ContextAssembler
from alphaforge.agents.providers.structured import CompletionPolicy, StructuredModelClient
from alphaforge.schemas.agent_outputs import (
    CandidateDesign,
    CodeRiskReview,
    CodeRiskReviewRequest,
    DesignRequest,
    PostBacktestAnalysis,
    PostBacktestAnalysisRequest,
)
from alphaforge.schemas.strategy_spec import StrictModel
from alphaforge.services.analysis_validator import validate_post_backtest_analysis

DESIGN_POLICY = CompletionPolicy("high", 6000)
RISK_POLICY = CompletionPolicy("high", 10000)
ANALYSIS_POLICY = CompletionPolicy("high", 10000)


class LLMStrategyDesigner:
    def __init__(
        self,
        client: StructuredModelClient,
        context_assembler: ContextAssembler | None = None,
    ) -> None:
        self.client = client
        self.context_assembler = context_assembler or ContextAssembler()

    def design(self, request: DesignRequest) -> CandidateDesign:
        context = self.context_assembler.build(
            agent_role="strategy_designer",
            candidate_type=request.candidate_type,
        )
        return self.client.complete(
            output_model=CandidateDesign,
            payload=request.model_dump(mode="json"),
            operation="strategy_design",
            policy=DESIGN_POLICY,
            context_bundle=context,
        )


class LLMCodeRiskAgent:
    def __init__(
        self,
        client: StructuredModelClient,
        context_assembler: ContextAssembler | None = None,
    ) -> None:
        self.client = client
        self.context_assembler = context_assembler or ContextAssembler()

    def review(self, request: CodeRiskReviewRequest) -> CodeRiskReview:
        from alphaforge.schemas.agent_outputs import CodeRiskFinding

        class ReviewDraft(StrictModel):
            verdict: Literal["approve", "changes_required", "reject"]
            findings: tuple[CodeRiskFinding, ...]

        route = request.strategy_spec.candidate_type
        context = self.context_assembler.build(
            agent_role="code_risk",
            candidate_type=route,
            template_version=request.generated_code.template_version,
        )
        draft = self.client.complete(
            output_model=ReviewDraft,
            payload=request.model_dump(mode="json"),
            operation="code_risk_review",
            policy=RISK_POLICY,
            context_bundle=context,
        )
        return CodeRiskReview(
            strategy_id=request.strategy_spec.strategy_id,
            reviewed_source_sha256=request.generated_code.source_sha256,
            spec_sha256=request.generated_code.spec_sha256,
            verdict=draft.verdict,
            findings=draft.findings,
        )


class LLMPostBacktestAnalysisAgent:
    def __init__(
        self,
        client: StructuredModelClient,
        context_assembler: ContextAssembler | None = None,
    ) -> None:
        self.client = client
        self.context_assembler = context_assembler or ContextAssembler()

    def analyze(self, request: PostBacktestAnalysisRequest) -> PostBacktestAnalysis:
        context = self.context_assembler.build(agent_role="post_backtest_analysis")

        def validate_analysis(analysis: PostBacktestAnalysis) -> None:
            errors = validate_post_backtest_analysis(request, analysis)
            if errors:
                raise ValueError(",".join(errors))

        return self.client.complete(
            output_model=PostBacktestAnalysis,
            payload=request.model_dump(mode="json"),
            operation="post_backtest_analysis",
            policy=ANALYSIS_POLICY,
            context_bundle=context,
            result_validator=validate_analysis,
        )
