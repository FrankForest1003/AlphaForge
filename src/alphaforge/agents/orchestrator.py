from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import threading

from alphaforge.codegen.code_validator import DEFAULT_ALLOWED_QC_API, validate_generated_code
from alphaforge.codegen.compiler import DeterministicStrategyCompiler
from alphaforge.codegen.template_renderer import QCTemplateRenderer
from alphaforge.ports import (
    BacktestProvider,
    CodeRiskAgent,
    PostBacktestAnalysisAgent,
    StrategyCompiler,
    StrategyDesigner,
)
from alphaforge.schemas.agent_outputs import (
    AuditEvent,
    CandidateRun,
    CodeRiskReviewRequest,
    OptimizationResult,
    PostBacktestAnalysisRequest,
    PriorDesignAttempt,
    RouteOutcome,
    StrategyCompilationRequest,
    TemplateCapabilityRecord,
    TemplateCapabilityReport,
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
from alphaforge.strategy_spec.versioning import strategy_semantic_digest, strategy_spec_digest


class OptimisationOrchestrator:
    ROUTES = ("traditional", "ml", "hybrid")
    REQUIRED_EVIDENCE_ROLES = {"user", "baseline_b1", "baseline_b2", "baseline_b3", "baseline_b4"}

    def __init__(
        self,
        *,
        designer: StrategyDesigner,
        strategy_compiler: StrategyCompiler | None = None,
        code_risk_agent: CodeRiskAgent,
        backtest_provider: BacktestProvider,
        analysis_agent: PostBacktestAnalysisAgent,
        lean_environment: LeanEnvironmentManifest,
        allowed_qc_api: tuple[str, ...] = DEFAULT_ALLOWED_QC_API,
        template_renderer: QCTemplateRenderer | None = None,
        evidence_summarizer: EvidenceSummarizer | None = None,
        spec_builder: SpecBuilder | None = None,
        selector: CandidateSelector | None = None,
        audit_sink: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self.designer = designer
        self.template_renderer = template_renderer or QCTemplateRenderer()
        self.strategy_compiler = strategy_compiler or DeterministicStrategyCompiler(
            self.template_renderer
        )
        self.code_risk_agent = code_risk_agent
        self.backtest_provider = backtest_provider
        self.analysis_agent = analysis_agent
        self.lean_environment = lean_environment
        self.allowed_qc_api = allowed_qc_api
        self.evidence_summarizer = evidence_summarizer or EvidenceSummarizer()
        self.spec_builder = spec_builder or SpecBuilder()
        self.selector = selector or CandidateSelector()
        self.audit_sink = audit_sink
        self._audit_lock = threading.Lock()

    def run(
        self,
        request: OptimizationRequest,
        *,
        initial_result: OptimizationResult | None = None,
        routes: tuple[str, ...] | None = None,
    ) -> OptimizationResult:
        self._validate_request_evidence(request)
        audit: list[AuditEvent] = (
            list(initial_result.audit_log) if initial_result is not None else []
        )
        evidence_summary = self.evidence_summarizer.summarize(
            request.evidence, request.reference_specs
        )
        self._audit(
            audit,
            "evidence_summary",
            request.optimization_id,
            "completed",
            "seven metrics summarized from five validation runs",
        )

        accumulated: list[CandidateRun] = (
            list(initial_result.candidates) if initial_result is not None else []
        )
        start_round = (
            max(candidate.round_number for candidate in accumulated) + 1
            if accumulated
            else 1
        )
        active_routes = routes or self.ROUTES
        if not active_routes or any(route not in self.ROUTES for route in active_routes):
            raise ValueError("routes must be a non-empty subset of the registered routes")
        for round_number in range(start_round, request.constraints.max_rounds + 1):
            with ThreadPoolExecutor(
                max_workers=len(active_routes),
                thread_name_prefix=f"alphaforge-round-{round_number}",
            ) as executor:
                futures = {
                    route: executor.submit(
                        self._run_route,
                        route=route,
                        round_number=round_number,
                        prior_candidates=tuple(accumulated),
                        request=request,
                        evidence_summary=evidence_summary,
                        audit=audit,
                    )
                    for route in active_routes
                }
                candidates_by_route = {
                    route: future.result() for route, future in futures.items()
                }
            accumulated.extend(candidates_by_route[route] for route in active_routes)
            interim_selection = self.selector.select(
                evidence=request.evidence,
                candidates=tuple(accumulated),
                constraints=request.constraints,
            )
            if interim_selection.selected_strategy_id is not None:
                self._audit(
                    audit,
                    "iteration_stop",
                    request.optimization_id,
                    "selected",
                    f"round {round_number}: {interim_selection.selected_strategy_id}",
                )
                break
        candidates = tuple(accumulated)
        route_outcomes = tuple(
            RouteOutcome(
                round_number=candidate.round_number,
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
            analysis = None
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
            template_capability_report=self._capability_report(finalized),
        )

    def _run_route(
        self,
        *,
        route: str,
        round_number: int,
        prior_candidates: tuple[CandidateRun, ...],
        request: OptimizationRequest,
        evidence_summary,
        audit: list[AuditEvent],
    ) -> CandidateRun:
        try:
            design = self.designer.design(
                self._design_request(
                    route=route,
                    round_number=round_number,
                    prior_candidates=prior_candidates,
                    request=request,
                    evidence_summary=evidence_summary,
                )
            )
        except Exception as exc:
            return self._design_failure(route, round_number, exc, audit)
        self._audit(
            audit,
            "strategy_design",
            f"{route}:r{round_number}",
            "completed",
            "CandidateDesign validated",
        )

        try:
            built = self.spec_builder.build(
                optimization_id=request.optimization_id,
                parent_spec=request.parent_spec,
                design=design,
                round_number=round_number,
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
                    round_number=round_number,
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
                round_number=round_number,
                state="rejected_by_spec",
                design=design,
                failure_reasons=(reason,),
            )
        semantic_sha256 = strategy_semantic_digest(built.spec)
        duplicate = self._find_duplicate(
            semantic_sha256=semantic_sha256,
            request=request,
            prior_candidates=prior_candidates,
        )
        if duplicate is not None:
            self._audit(
                audit,
                "semantic_deduplication",
                built.spec.strategy_id,
                "duplicate",
                duplicate,
            )
            return CandidateRun(
                candidate_type=route,
                round_number=round_number,
                state="duplicate_of_reference",
                design=design,
                strategy_spec=built.spec,
                changed_paths=built.changed_paths,
                failure_reasons=(f"SEMANTIC_DUPLICATE:{duplicate}",),
                semantic_sha256=semantic_sha256,
                duplicate_of_strategy_id=duplicate,
            )
        self._audit(audit, "spec_validation", built.spec.strategy_id, "completed", "spec approved")

        template_version = self.template_renderer.template_version(route)
        compilation_request = StrategyCompilationRequest(
            strategy_spec=built.spec,
            spec_sha256=strategy_spec_digest(built.spec),
            lean_environment=self.lean_environment,
            allowed_qc_api=self.allowed_qc_api,
            template_version=template_version,
            template_sha256=self.template_renderer.template_sha256(route),
            semantics_version=self.template_renderer.SEMANTICS_VERSION,
        )
        try:
            code = self.strategy_compiler.compile(compilation_request)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._audit(audit, "strategy_compilation", built.spec.strategy_id, "failed", reason)
            return CandidateRun(
                candidate_type=route,
                round_number=round_number,
                state="rejected_by_code_validation",
                design=design,
                strategy_spec=built.spec,
                changed_paths=built.changed_paths,
                failure_reasons=(reason,),
                semantic_sha256=semantic_sha256,
            )
        self._audit(audit, "strategy_compilation", built.spec.strategy_id, "completed", code.source_sha256)

        code_validation = validate_generated_code(
            built.spec,
            code,
            allowed_qc_api=self.allowed_qc_api,
            allowed_imports=self.lean_environment.allowed_imports,
        )
        if not code_validation.valid:
            return self._code_failure(
                route=route,
                state="rejected_by_code_validation",
                built=built,
                code=code,
                validation=code_validation,
                risk_review=None,
                smoke=None,
                reasons=code_validation.errors,
                audit=audit,
            )

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
                smoke=None,
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
                    code_risk_review.spec_sha256 != compilation_request.spec_sha256,
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
                smoke=None,
                reasons=review_binding_errors,
                audit=audit,
            )
        if code_risk_review.verdict != "approve":
            reasons = tuple(
                f"{finding.code}:{finding.required_correction}"
                for finding in code_risk_review.findings
                if finding.severity == "blocking"
            ) or ("CODE_RISK_REJECTED",)
            return self._code_failure(
                route=route,
                state="rejected_by_code_risk",
                built=built,
                code=code,
                validation=code_validation,
                risk_review=code_risk_review,
                smoke=None,
                reasons=reasons,
                audit=audit,
            )

        smoke = self.backtest_provider.smoke_test(built.spec, code)
        self._audit(
            audit,
            "lean_smoke_test",
            built.spec.strategy_id,
            smoke.status,
            ",".join(smoke.diagnostics) or "smoke test passed",
        )
        if smoke.status == "failed":
            return self._code_failure(
                route=route,
                state="rejected_by_smoke_test",
                built=built,
                code=code,
                validation=code_validation,
                risk_review=code_risk_review,
                smoke=smoke,
                reasons=smoke.diagnostics or ("LEAN_SMOKE_FAILED",),
                audit=audit,
            )

        result = self.backtest_provider.run(built.spec, code)
        self._audit(audit, "full_backtest", built.spec.strategy_id, result.status, result.run_id)
        if result.status != "completed" or result.metrics is None:
            reasons = result.warnings or ("BACKTEST_RESULT_INCOMPLETE",)
            return self._code_failure(
                route=route,
                state="rejected_by_backtest",
                built=built,
                code=code,
                validation=code_validation,
                risk_review=code_risk_review,
                smoke=smoke,
                reasons=reasons,
                audit=audit,
                backtest_result=result,
            )
        return CandidateRun(
            candidate_type=route,
            round_number=round_number,
            state="backtested_not_selected",
            design=design,
            strategy_spec=built.spec,
            changed_paths=built.changed_paths,
            generated_code=code,
            code_validation=code_validation,
            code_risk_review=code_risk_review,
            smoke_test=smoke,
            backtest_result=result,
            semantic_sha256=semantic_sha256,
        )

    def _design_request(
        self,
        *,
        route: str,
        round_number: int,
        prior_candidates: tuple[CandidateRun, ...],
        request: OptimizationRequest,
        evidence_summary,
    ):
        from alphaforge.schemas.agent_outputs import DesignRequest

        return DesignRequest(
            optimization_id=request.optimization_id,
            candidate_type=route,
            round_number=round_number,
            parent_spec=request.parent_spec,
            constraints=request.constraints,
            evidence_summary=evidence_summary,
            prior_attempts=tuple(
                PriorDesignAttempt(
                    round_number=candidate.round_number,
                    candidate_type=candidate.candidate_type,
                    strategy_spec=candidate.strategy_spec,
                    semantic_sha256=candidate.semantic_sha256
                    or strategy_semantic_digest(candidate.strategy_spec),
                    state=candidate.state,
                    backtest_result=candidate.backtest_result,
                )
                for candidate in prior_candidates
                if candidate.candidate_type == route and candidate.strategy_spec is not None
            ),
        )

    def _design_failure(self, route, round_number, exc, audit):
        reason = f"{type(exc).__name__}: {exc}"
        self._audit(audit, "strategy_design", f"{route}:r{round_number}", "failed", reason)
        return CandidateRun(
            candidate_type=route,
            round_number=round_number,
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
        backtest_result=None,
    ):
        self._audit(audit, state, built.spec.strategy_id, "rejected", ",".join(reasons))
        return CandidateRun(
            candidate_type=route,
            round_number=int(built.spec.strategy_id.rsplit("_r", 1)[-1]),
            state=state,
            design=built.design,
            strategy_spec=built.spec,
            changed_paths=built.changed_paths,
            generated_code=code,
            code_validation=validation,
            code_risk_review=risk_review,
            smoke_test=smoke,
            backtest_result=backtest_result,
            failure_reasons=reasons,
            semantic_sha256=strategy_semantic_digest(built.spec),
        )

    def _find_duplicate(
        self,
        *,
        semantic_sha256: str,
        request: OptimizationRequest,
        prior_candidates: tuple[CandidateRun, ...],
    ) -> str | None:
        for spec in request.reference_specs:
            if strategy_semantic_digest(spec) == semantic_sha256:
                return spec.strategy_id
        for candidate in prior_candidates:
            if candidate.strategy_spec is None:
                continue
            if strategy_semantic_digest(candidate.strategy_spec) == semantic_sha256:
                return candidate.strategy_spec.strategy_id
        return None

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
        evidence_ids = {result.strategy_id for result in request.evidence}
        spec_ids = {spec.strategy_id for spec in request.reference_specs}
        if evidence_ids != spec_ids:
            raise ValueError("reference spec IDs must exactly match evidence strategy IDs")

    def _capability_report(self, candidates) -> TemplateCapabilityReport:
        records = []
        for candidate in candidates:
            reasons = candidate.failure_reasons
            if candidate.generated_code is not None:
                status = "rendered"
                reasons = ()
            elif candidate.state == "duplicate_of_reference":
                status = "duplicate"
            elif any("CANNOT_IMPLEMENT" in reason for reason in reasons):
                status = "cannot_implement"
            else:
                status = "template_error"
            records.append(
                TemplateCapabilityRecord(
                    candidate_type=candidate.candidate_type,
                    status=status,
                    reasons=reasons,
                )
            )
        return TemplateCapabilityReport(template_version="route_templates_v1", records=tuple(records))

    def _audit(self, events, stage, subject_id, outcome, detail) -> None:
        with self._audit_lock:
            event = AuditEvent(
                sequence=len(events) + 1,
                stage=stage,
                subject_id=subject_id,
                outcome=outcome,
                detail=detail,
            )
            events.append(event)
            if self.audit_sink is not None:
                self.audit_sink(event)
