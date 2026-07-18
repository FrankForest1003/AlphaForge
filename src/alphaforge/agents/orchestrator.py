from __future__ import annotations

from alphaforge.codegen.code_validator import DEFAULT_ALLOWED_QC_API, validate_generated_code
from alphaforge.ports import (
    BacktestProvider,
    CodeRiskAgent,
    PostBacktestAnalysisAgent,
    QCCodeAgent,
    RepairAgent,
    StrategyDesigner,
)
from alphaforge.schemas.agent_outputs import (
    AuditEvent,
    CandidateRun,
    CodeRiskReviewRequest,
    OptimizationResult,
    PostBacktestAnalysisRequest,
    QCCodeGenerationRequest,
    RepairRequest,
    RouteOutcome,
)
from alphaforge.schemas.manifests import LeanEnvironmentManifest
from alphaforge.schemas.optimisation import OptimizationRequest
from alphaforge.services import (
    CandidateSelector,
    EvidenceSummarizer,
    SpecBuilder,
    validate_post_backtest_analysis,
)
from alphaforge.strategy_spec.validator import validate_strategy_spec
from alphaforge.strategy_spec.versioning import strategy_spec_digest


class OptimisationOrchestrator:
    ROUTES = ("traditional", "ml", "hybrid")
    REQUIRED_EVIDENCE_ROLES = {"user", "baseline_b1", "baseline_b2", "baseline_b3", "baseline_b4"}

    def __init__(
        self,
        *,
        designer: StrategyDesigner,
        qc_code_agent: QCCodeAgent,
        code_risk_agent: CodeRiskAgent,
        repair_agent: RepairAgent,
        backtest_provider: BacktestProvider,
        analysis_agent: PostBacktestAnalysisAgent,
        lean_environment: LeanEnvironmentManifest,
        allowed_qc_api: tuple[str, ...] = DEFAULT_ALLOWED_QC_API,
        template_version: str = "qc_template_v1",
        evidence_summarizer: EvidenceSummarizer | None = None,
        spec_builder: SpecBuilder | None = None,
        selector: CandidateSelector | None = None,
    ) -> None:
        self.designer = designer
        self.qc_code_agent = qc_code_agent
        self.code_risk_agent = code_risk_agent
        self.repair_agent = repair_agent
        self.backtest_provider = backtest_provider
        self.analysis_agent = analysis_agent
        self.lean_environment = lean_environment
        self.allowed_qc_api = allowed_qc_api
        self.template_version = template_version
        self.evidence_summarizer = evidence_summarizer or EvidenceSummarizer()
        self.spec_builder = spec_builder or SpecBuilder()
        self.selector = selector or CandidateSelector()

    def run(self, request: OptimizationRequest) -> OptimizationResult:
        self._validate_request_evidence(request)
        audit: list[AuditEvent] = []
        evidence_summary = self.evidence_summarizer.summarize(request.evidence)
        self._audit(
            audit,
            "evidence_summary",
            request.optimization_id,
            "completed",
            "seven metrics summarized from five validation runs",
        )

        candidates = tuple(
            self._run_route(
                route=route,
                request=request,
                evidence_summary=evidence_summary,
                audit=audit,
            )
            for route in self.ROUTES
        )
        route_outcomes = tuple(
            RouteOutcome(
                candidate_type=candidate.candidate_type,
                state=candidate.state,
                strategy_spec=candidate.strategy_spec,
                changed_paths=candidate.changed_paths,
                backtest_result=candidate.backtest_result,
                failure_reasons=candidate.failure_reasons,
            )
            for candidate in candidates
        )

        analysis = None
        analysis_error = None
        try:
            analysis_request = PostBacktestAnalysisRequest(
                optimization_id=request.optimization_id,
                parent_spec=request.parent_spec,
                evidence=request.evidence,
                route_outcomes=route_outcomes,
            )
            analysis = self.analysis_agent.analyze(analysis_request)
            analysis_errors = validate_post_backtest_analysis(analysis_request, analysis)
            if analysis_errors:
                raise ValueError(",".join(analysis_errors))
            self._audit(
                audit,
                "post_backtest_analysis",
                request.optimization_id,
                "completed",
                "all route outcomes analyzed in one call",
            )
        except Exception as exc:
            analysis_error = f"{type(exc).__name__}: {exc}"
            self._audit(
                audit,
                "post_backtest_analysis",
                request.optimization_id,
                "failed",
                analysis_error,
            )

        selection = self.selector.select(
            evidence=request.evidence,
            candidates=candidates,
            constraints=request.constraints,
        )
        finalized = tuple(
            candidate.model_copy(
                update={
                    "state": (
                        "selected"
                        if candidate.strategy_spec is not None
                        and candidate.strategy_spec.strategy_id == selection.selected_strategy_id
                        else candidate.state
                    )
                }
            )
            for candidate in candidates
        )
        self._audit(
            audit,
            "candidate_selection",
            request.optimization_id,
            "completed",
            selection.selected_strategy_id or "no robust improvement",
        )
        return OptimizationResult(
            optimization_id=request.optimization_id,
            status="completed" if analysis is not None else "failed",
            evidence_summary=evidence_summary,
            candidates=finalized,
            post_backtest_analysis=analysis,
            selection=selection,
            analysis_error=analysis_error,
            audit_log=tuple(audit),
        )

    def _run_route(
        self,
        *,
        route: str,
        request: OptimizationRequest,
        evidence_summary,
        audit: list[AuditEvent],
    ) -> CandidateRun:
        try:
            design = self.designer.design(
                self._design_request(
                    route=route,
                    request=request,
                    evidence_summary=evidence_summary,
                )
            )
        except Exception as exc:
            return self._design_failure(route, exc, audit)
        self._audit(audit, "strategy_design", route, "completed", "CandidateDesign validated")

        try:
            built = self.spec_builder.build(
                optimization_id=request.optimization_id,
                parent_spec=request.parent_spec,
                design=design,
            )
            issues = validate_strategy_spec(
                built.spec,
                parent=request.parent_spec,
                changed_paths=built.changed_paths,
            )
            if issues:
                reasons = tuple(f"{issue.code}:{issue.path}" for issue in issues)
                self._audit(audit, "spec_validation", route, "rejected", ",".join(reasons))
                return CandidateRun(
                    candidate_type=route,
                    state="rejected_by_spec",
                    design=design,
                    strategy_spec=built.spec,
                    changed_paths=built.changed_paths,
                    failure_reasons=reasons,
                )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._audit(audit, "spec_build", route, "rejected", reason)
            return CandidateRun(
                candidate_type=route,
                state="rejected_by_spec",
                design=design,
                failure_reasons=(reason,),
            )
        self._audit(audit, "spec_validation", built.spec.strategy_id, "completed", "spec approved")

        generation_request = QCCodeGenerationRequest(
            strategy_spec=built.spec,
            spec_sha256=strategy_spec_digest(built.spec),
            lean_environment=self.lean_environment,
            allowed_qc_api=self.allowed_qc_api,
            template_version=self.template_version,
        )
        try:
            code = self.qc_code_agent.generate(generation_request)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._audit(audit, "qc_code_generation", built.spec.strategy_id, "failed", reason)
            return CandidateRun(
                candidate_type=route,
                state="rejected_by_code_validation",
                design=design,
                strategy_spec=built.spec,
                changed_paths=built.changed_paths,
                failure_reasons=(reason,),
            )
        self._audit(audit, "qc_code_generation", built.spec.strategy_id, "completed", code.source_sha256)

        attempts = 0
        code_validation = None
        code_risk_review = None
        smoke = None
        while True:
            code_validation = validate_generated_code(
                built.spec,
                code,
                allowed_qc_api=self.allowed_qc_api,
            )
            if not code_validation.valid:
                if attempts >= request.constraints.max_repair_attempts:
                    return self._code_failure(
                        route=route,
                        state="rejected_by_code_validation",
                        built=built,
                        code=code,
                        validation=code_validation,
                        risk_review=code_risk_review,
                        smoke=smoke,
                        reasons=code_validation.errors,
                        audit=audit,
                    )
                attempts += 1
                code = self._repair(
                    spec=built.spec,
                    code=code,
                    source="static_validation",
                    diagnostics=code_validation.errors,
                    attempt=attempts,
                    audit=audit,
                )
                if code is None:
                    return self._code_failure(
                        route=route,
                        state="rejected_by_code_validation",
                        built=built,
                        code=None,
                        validation=code_validation,
                        risk_review=code_risk_review,
                        smoke=smoke,
                        reasons=("REPAIR_FAILED",),
                        audit=audit,
                    )
                continue

            try:
                code_risk_review = self.code_risk_agent.review(
                    CodeRiskReviewRequest(
                        strategy_spec=built.spec,
                        generated_code=code,
                        static_validation=code_validation,
                        lean_environment=self.lean_environment,
                    )
                )
            except Exception as exc:
                return self._code_failure(
                    route=route,
                    state="rejected_by_code_risk",
                    built=built,
                    code=code,
                    validation=code_validation,
                    risk_review=None,
                    smoke=smoke,
                    reasons=(f"{type(exc).__name__}: {exc}",),
                    audit=audit,
                )
            self._audit(
                audit,
                "code_risk_review",
                built.spec.strategy_id,
                code_risk_review.verdict,
                ",".join(finding.code for finding in code_risk_review.findings) or "no findings",
            )
            review_binding_errors = tuple(
                error
                for condition, error in (
                    (
                        code_risk_review.strategy_id != built.spec.strategy_id,
                        "RISK_REVIEW_STRATEGY_ID_MISMATCH",
                    ),
                    (
                        code_risk_review.spec_sha256 != generation_request.spec_sha256,
                        "RISK_REVIEW_SPEC_DIGEST_MISMATCH",
                    ),
                    (
                        code_risk_review.reviewed_source_sha256 != code.source_sha256,
                        "RISK_REVIEW_SOURCE_DIGEST_MISMATCH",
                    ),
                )
                if condition
            )
            if review_binding_errors:
                return self._code_failure(
                    route=route,
                    state="rejected_by_code_risk",
                    built=built,
                    code=code,
                    validation=code_validation,
                    risk_review=code_risk_review,
                    smoke=smoke,
                    reasons=review_binding_errors,
                    audit=audit,
                )
            if code_risk_review.verdict == "reject":
                return self._code_failure(
                    route=route,
                    state="rejected_by_code_risk",
                    built=built,
                    code=code,
                    validation=code_validation,
                    risk_review=code_risk_review,
                    smoke=smoke,
                    reasons=tuple(finding.code for finding in code_risk_review.findings) or ("CODE_RISK_REJECTED",),
                    audit=audit,
                )
            if code_risk_review.verdict == "repair_required":
                diagnostics = tuple(
                    f"{finding.code}:{finding.repair_instruction}"
                    for finding in code_risk_review.findings
                    if finding.severity == "blocking"
                )
                if attempts >= request.constraints.max_repair_attempts:
                    return self._code_failure(
                        route=route,
                        state="rejected_by_code_risk",
                        built=built,
                        code=code,
                        validation=code_validation,
                        risk_review=code_risk_review,
                        smoke=smoke,
                        reasons=diagnostics,
                        audit=audit,
                    )
                attempts += 1
                code = self._repair(
                    spec=built.spec,
                    code=code,
                    source="code_risk",
                    diagnostics=diagnostics,
                    attempt=attempts,
                    audit=audit,
                )
                if code is None:
                    return self._code_failure(
                        route=route,
                        state="rejected_by_code_risk",
                        built=built,
                        code=None,
                        validation=code_validation,
                        risk_review=code_risk_review,
                        smoke=smoke,
                        reasons=("REPAIR_FAILED",),
                        audit=audit,
                    )
                continue

            smoke = self.backtest_provider.smoke_test(built.spec, code)
            self._audit(
                audit,
                "lean_smoke_test",
                built.spec.strategy_id,
                smoke.status,
                ",".join(smoke.diagnostics) or "smoke test passed",
            )
            if smoke.status == "failed":
                if attempts >= request.constraints.max_repair_attempts:
                    return self._code_failure(
                        route=route,
                        state="rejected_by_smoke_test",
                        built=built,
                        code=code,
                        validation=code_validation,
                        risk_review=code_risk_review,
                        smoke=smoke,
                        reasons=smoke.diagnostics,
                        audit=audit,
                    )
                attempts += 1
                code = self._repair(
                    spec=built.spec,
                    code=code,
                    source="smoke_test",
                    diagnostics=smoke.diagnostics or ("LEAN_SMOKE_FAILED",),
                    attempt=attempts,
                    audit=audit,
                )
                if code is None:
                    return self._code_failure(
                        route=route,
                        state="rejected_by_smoke_test",
                        built=built,
                        code=None,
                        validation=code_validation,
                        risk_review=code_risk_review,
                        smoke=smoke,
                        reasons=("REPAIR_FAILED",),
                        audit=audit,
                    )
                continue
            break

        result = self.backtest_provider.run(built.spec, code)
        self._audit(audit, "full_backtest", built.spec.strategy_id, result.status, result.run_id)
        return CandidateRun(
            candidate_type=route,
            state="backtested_not_selected",
            design=design,
            strategy_spec=built.spec,
            changed_paths=built.changed_paths,
            generated_code=code,
            code_validation=code_validation,
            code_risk_review=code_risk_review,
            smoke_test=smoke,
            backtest_result=result,
        )

    def _design_request(self, *, route: str, request: OptimizationRequest, evidence_summary):
        from alphaforge.schemas.agent_outputs import DesignRequest

        return DesignRequest(
            optimization_id=request.optimization_id,
            candidate_type=route,
            parent_spec=request.parent_spec,
            evidence_summary=evidence_summary,
        )

    def _repair(self, *, spec, code, source, diagnostics, attempt, audit):
        try:
            repaired = self.repair_agent.repair(
                RepairRequest(
                    strategy_spec=spec,
                    failed_code=code,
                    lean_environment=self.lean_environment,
                    failure_source=source,
                    diagnostics=diagnostics,
                    attempt=attempt,
                )
            )
            self._audit(audit, "code_repair", spec.strategy_id, "completed", f"attempt={attempt}; source={source}")
            return repaired
        except Exception as exc:
            self._audit(audit, "code_repair", spec.strategy_id, "failed", f"{type(exc).__name__}: {exc}")
            return None

    def _design_failure(self, route, exc, audit):
        reason = f"{type(exc).__name__}: {exc}"
        self._audit(audit, "strategy_design", route, "failed", reason)
        return CandidateRun(
            candidate_type=route,
            state="rejected_by_design",
            failure_reasons=(reason,),
        )

    def _code_failure(
        self,
        *,
        route,
        state,
        built,
        code,
        validation,
        risk_review,
        smoke,
        reasons,
        audit,
    ):
        self._audit(audit, state, built.spec.strategy_id, "rejected", ",".join(reasons))
        return CandidateRun(
            candidate_type=route,
            state=state,
            design=built.design,
            strategy_spec=built.spec,
            changed_paths=built.changed_paths,
            generated_code=code,
            code_validation=validation,
            code_risk_review=risk_review,
            smoke_test=smoke,
            failure_reasons=reasons,
        )

    def _validate_request_evidence(self, request: OptimizationRequest) -> None:
        if any(result.dataset_split == "test" for result in request.evidence):
            raise ValueError("test-set evidence is forbidden during optimisation")
        roles = {result.strategy_role for result in request.evidence}
        if roles != self.REQUIRED_EVIDENCE_ROLES:
            missing = sorted(self.REQUIRED_EVIDENCE_ROLES - roles)
            extra = sorted(roles - self.REQUIRED_EVIDENCE_ROLES)
            raise ValueError(f"evidence roles mismatch; missing={missing}, extra={extra}")
        if any(result.status != "completed" or result.metrics is None for result in request.evidence):
            raise ValueError("all five evidence results must be completed and contain metrics")

    @staticmethod
    def _audit(events, stage, subject_id, outcome, detail) -> None:
        events.append(
            AuditEvent(
                sequence=len(events) + 1,
                stage=stage,
                subject_id=subject_id,
                outcome=outcome,
                detail=detail,
            )
        )
