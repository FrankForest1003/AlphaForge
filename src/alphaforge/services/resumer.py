from __future__ import annotations

from collections.abc import Callable

from alphaforge.ports import BacktestProvider, CodeRiskAgent, PostBacktestAnalysisAgent
from alphaforge.schemas.agent_outputs import (
    AuditEvent,
    CandidateRun,
    CodeRiskReviewRequest,
    OptimizationResult,
    PostBacktestAnalysisRequest,
    RouteOutcome,
)
from alphaforge.schemas.manifests import LeanEnvironmentManifest
from alphaforge.schemas.optimisation import OptimizationConstraints
from alphaforge.services.analysis_validator import validate_post_backtest_analysis
from alphaforge.services.candidate_selector import CandidateSelector


class OptimizationResumer:
    """Resume narrowly recognized pipeline failures without repeating model design."""

    def __init__(
        self,
        *,
        backtest_provider: BacktestProvider,
        analysis_agent: PostBacktestAnalysisAgent,
        lean_environment: LeanEnvironmentManifest | None = None,
        selector: CandidateSelector | None = None,
        audit_sink: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self.backtest_provider = backtest_provider
        self.analysis_agent = analysis_agent
        self.lean_environment = lean_environment
        self.selector = selector or CandidateSelector()
        self.audit_sink = audit_sink

    def resume_supported_failures(
        self,
        result: OptimizationResult,
        *,
        constraints: OptimizationConstraints,
        code_risk_agent: CodeRiskAgent,
    ) -> OptimizationResult:
        if any(self._is_completion_marker_false_positive(item) for item in result.candidates):
            return self.resume_completion_marker_risk_false_positive(
                result,
                constraints=constraints,
                code_risk_agent=code_risk_agent,
            )
        return self.resume_smoke_contract_failures(result, constraints=constraints)

    def resume_smoke_contract_failures(
        self,
        result: OptimizationResult,
        *,
        constraints: OptimizationConstraints,
    ) -> OptimizationResult:
        audit = list(result.audit_log)
        candidates: list[CandidateRun] = []
        for candidate in result.candidates:
            if not self._is_resumable(candidate):
                candidates.append(candidate)
                continue
            assert candidate.strategy_spec is not None
            assert candidate.generated_code is not None
            assert candidate.smoke_test is not None
            recover_full = getattr(self.backtest_provider, "recover_latest_full", None)
            recovered = recover_full(candidate.strategy_spec) if callable(recover_full) else None
            if recovered is not None:
                self._audit(
                    audit,
                    "recovered_full_backtest",
                    candidate.strategy_spec.strategy_id,
                    "completed",
                    recovered.run_id,
                )
                candidates.append(
                    candidate.model_copy(
                        update={
                            "state": "backtested_not_selected",
                            "smoke_test": candidate.smoke_test.model_copy(
                                update={"status": "passed", "diagnostics": ()}
                            ),
                            "backtest_result": recovered,
                            "failure_reasons": (),
                        }
                    )
                )
                continue
            recover_smoke = getattr(self.backtest_provider, "recover_latest_smoke", None)
            recovered_smoke = (
                recover_smoke(candidate.strategy_spec) if callable(recover_smoke) else None
            )
            if recovered_smoke is not None and recovered_smoke.status == "failed":
                self._audit(
                    audit,
                    "recovered_lean_smoke_test",
                    candidate.strategy_spec.strategy_id,
                    "failed",
                    ",".join(recovered_smoke.diagnostics),
                )
                candidates.append(
                    candidate.model_copy(
                        update={
                            "smoke_test": recovered_smoke,
                            "failure_reasons": recovered_smoke.diagnostics,
                        }
                    )
                )
                continue
            smoke = recovered_smoke or self.backtest_provider.smoke_test(
                candidate.strategy_spec, candidate.generated_code
            )
            self._audit(
                audit,
                (
                    "recovered_lean_smoke_test"
                    if recovered_smoke is not None
                    else "resumed_lean_smoke_test"
                ),
                candidate.strategy_spec.strategy_id,
                smoke.status,
                ",".join(smoke.diagnostics) or "smoke test passed",
            )
            if smoke.status != "passed":
                candidates.append(
                    candidate.model_copy(
                        update={
                            "smoke_test": smoke,
                            "failure_reasons": smoke.diagnostics,
                        }
                    )
                )
                continue
            backtest = self.backtest_provider.run(
                candidate.strategy_spec, candidate.generated_code
            )
            self._audit(
                audit,
                "resumed_full_backtest",
                candidate.strategy_spec.strategy_id,
                backtest.status,
                backtest.run_id,
            )
            completed = backtest.status == "completed" and backtest.metrics is not None
            candidates.append(
                candidate.model_copy(
                    update={
                        "state": (
                            "backtested_not_selected" if completed else "rejected_by_backtest"
                        ),
                        "smoke_test": smoke,
                        "backtest_result": backtest,
                        "failure_reasons": () if completed else backtest.warnings,
                    }
                )
            )

        return self._finalize(
            result=result,
            candidates=candidates,
            audit=audit,
            constraints=constraints,
            audit_prefix="resumed",
        )

    def resume_completion_marker_risk_false_positive(
        self,
        result: OptimizationResult,
        *,
        constraints: OptimizationConstraints,
        code_risk_agent: CodeRiskAgent,
    ) -> OptimizationResult:
        """Re-review only the known completion-marker Prompt false positive."""
        if self.lean_environment is None:
            raise ValueError("lean_environment is required for code-risk re-review")
        audit = list(result.audit_log)
        candidates: list[CandidateRun] = []
        for candidate in result.candidates:
            if not self._is_completion_marker_false_positive(candidate):
                candidates.append(candidate)
                continue
            assert candidate.strategy_spec is not None
            assert candidate.generated_code is not None
            assert candidate.code_validation is not None
            review = code_risk_agent.review(
                CodeRiskReviewRequest(
                    strategy_spec=candidate.strategy_spec,
                    generated_code=candidate.generated_code,
                    static_validation=candidate.code_validation,
                    lean_environment=self.lean_environment,
                )
            )
            binding_errors = tuple(
                error
                for condition, error in (
                    (
                        review.strategy_id != candidate.strategy_spec.strategy_id,
                        "RISK_REVIEW_STRATEGY_ID_MISMATCH",
                    ),
                    (
                        review.spec_sha256 != candidate.generated_code.spec_sha256,
                        "RISK_REVIEW_SPEC_DIGEST_MISMATCH",
                    ),
                    (
                        review.reviewed_source_sha256
                        != candidate.generated_code.source_sha256,
                        "RISK_REVIEW_SOURCE_DIGEST_MISMATCH",
                    ),
                )
                if condition
            )
            self._audit(
                audit,
                "resumed_code_risk_review",
                candidate.strategy_spec.strategy_id,
                review.verdict,
                ",".join(finding.code for finding in review.findings) or "no findings",
            )
            if binding_errors or review.verdict != "approve":
                reasons = binding_errors or tuple(
                    f"{finding.code}:{finding.required_correction}"
                    for finding in review.findings
                    if finding.severity == "blocking"
                ) or ("CODE_RISK_REJECTED",)
                candidates.append(
                    candidate.model_copy(
                        update={"code_risk_review": review, "failure_reasons": reasons}
                    )
                )
                continue
            smoke = self.backtest_provider.smoke_test(
                candidate.strategy_spec, candidate.generated_code
            )
            self._audit(
                audit,
                "resumed_lean_smoke_test",
                candidate.strategy_spec.strategy_id,
                smoke.status,
                ",".join(smoke.diagnostics) or "smoke test passed",
            )
            if smoke.status != "passed":
                candidates.append(
                    candidate.model_copy(
                        update={
                            "state": "rejected_by_smoke_test",
                            "code_risk_review": review,
                            "smoke_test": smoke,
                            "failure_reasons": smoke.diagnostics,
                        }
                    )
                )
                continue
            backtest = self.backtest_provider.run(
                candidate.strategy_spec, candidate.generated_code
            )
            self._audit(
                audit,
                "resumed_full_backtest",
                candidate.strategy_spec.strategy_id,
                backtest.status,
                backtest.run_id,
            )
            completed = backtest.status == "completed" and backtest.metrics is not None
            candidates.append(
                candidate.model_copy(
                    update={
                        "state": (
                            "backtested_not_selected" if completed else "rejected_by_backtest"
                        ),
                        "code_risk_review": review,
                        "smoke_test": smoke,
                        "backtest_result": backtest,
                        "failure_reasons": () if completed else backtest.warnings,
                    }
                )
            )
        return self._finalize(
            result=result,
            candidates=candidates,
            audit=audit,
            constraints=constraints,
            audit_prefix="risk_retry",
        )

    def _finalize(
        self,
        *,
        result: OptimizationResult,
        candidates: list[CandidateRun],
        audit: list[AuditEvent],
        constraints: OptimizationConstraints,
        audit_prefix: str,
    ) -> OptimizationResult:
        evidence = tuple(
            item.backtest_result for item in result.evidence_summary.reference_strategies
        )
        outcomes = tuple(
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
        analysis_request = PostBacktestAnalysisRequest(
            optimization_id=result.optimization_id,
            parent_spec=next(
                item.strategy_spec
                for item in result.evidence_summary.reference_strategies
                if item.strategy_role == "user"
            ),
            evidence=evidence,
            route_outcomes=outcomes,
        )
        analysis = None
        analysis_error = None
        try:
            analysis = self.analysis_agent.analyze(analysis_request)
            errors = validate_post_backtest_analysis(analysis_request, analysis)
            if errors:
                raise ValueError(",".join(errors))
            self._audit(
                audit,
                f"{audit_prefix}_post_backtest_analysis",
                result.optimization_id,
                "completed",
                "all original and resumed outcomes analyzed once",
            )
        except Exception as exc:
            analysis_error = f"{type(exc).__name__}: {exc}"
            self._audit(
                audit,
                f"{audit_prefix}_post_backtest_analysis",
                result.optimization_id,
                "failed",
                analysis_error,
            )
        selectable_candidates = tuple(
            candidate.model_copy(update={"state": "backtested_not_selected"})
            if candidate.state == "selected"
            else candidate
            for candidate in candidates
        )
        selection = self.selector.select(
            evidence=evidence,
            candidates=selectable_candidates,
            constraints=constraints,
        )
        finalized = tuple(
            candidate.model_copy(
                update={
                    "state": (
                        "selected"
                        if candidate.strategy_spec is not None
                        and candidate.strategy_spec.strategy_id
                        == selection.selected_strategy_id
                        else candidate.state
                    )
                }
            )
            for candidate in selectable_candidates
        )
        self._audit(
            audit,
            f"{audit_prefix}_candidate_selection",
            result.optimization_id,
            "completed",
            selection.selected_strategy_id or "no robust improvement",
        )
        return result.model_copy(
            update={
                "status": "completed" if analysis is not None else "failed",
                "candidates": finalized,
                "post_backtest_analysis": analysis,
                "selection": selection,
                "analysis_error": analysis_error,
                "audit_log": tuple(audit),
            }
        )

    @staticmethod
    def _is_completion_marker_false_positive(candidate: CandidateRun) -> bool:
        if (
            candidate.state != "rejected_by_code_risk"
            or candidate.strategy_spec is None
            or candidate.generated_code is None
            or candidate.code_validation is None
            or not candidate.code_validation.valid
            or candidate.code_risk_review is None
        ):
            return False
        blocking_codes = {
            finding.code
            for finding in candidate.code_risk_review.findings
            if finding.severity == "blocking"
        }
        marker = candidate.generated_code.compiler_metadata.get("completion_marker", "")
        return (
            blocking_codes == {"MISSING_COMPLETION_SIGNAL"}
            and bool(marker)
            and f'self.debug("{marker}")' in candidate.generated_code.source
        )

    @staticmethod
    def _is_resumable(candidate: CandidateRun) -> bool:
        return (
            candidate.state == "rejected_by_smoke_test"
            and candidate.strategy_spec is not None
            and candidate.generated_code is not None
            and candidate.code_validation is not None
            and candidate.code_validation.valid
            and candidate.code_risk_review is not None
            and candidate.code_risk_review.verdict == "approve"
            and any(
                "Generated source violates runtime contract" in reason
                and "self.target_gross = 0.95" in reason
                for reason in candidate.failure_reasons
            )
        )

    def _audit(self, events, stage, subject_id, outcome, detail) -> None:
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
