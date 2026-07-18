from __future__ import annotations

from alphaforge.codegen.code_validator import validate_generated_code
from alphaforge.ports import AgentProvider, BacktestProvider, CodeGenerationProvider, RepairProvider
from alphaforge.schemas.agent_outputs import (
    AuditEvent,
    CandidateRun,
    OptimizationResult,
    RepairRequest,
)
from alphaforge.schemas.optimisation import OptimizationRequest
from alphaforge.strategy_spec.validator import validate_strategy_spec


class OptimisationOrchestrator:
    ROUTES = ("traditional", "ml", "hybrid")
    REQUIRED_EVIDENCE_ROLES = {"user", "baseline_b1", "baseline_b2", "baseline_b3", "baseline_b4"}

    def __init__(
        self,
        *,
        agent_provider: AgentProvider,
        code_generator: CodeGenerationProvider,
        backtest_provider: BacktestProvider,
        repair_provider: RepairProvider | None = None,
    ) -> None:
        self.agent_provider = agent_provider
        self.code_generator = code_generator
        self.backtest_provider = backtest_provider
        self.repair_provider = repair_provider

    def run(self, request: OptimizationRequest) -> OptimizationResult:
        self._validate_request_evidence(request)
        audit: list[AuditEvent] = []

        analysis = self.agent_provider.analyze(request)
        self._audit(audit, "baseline_analysis", request.optimization_id, "completed", "5 validation results analyzed")

        candidates: list[CandidateRun] = []
        for route in self.ROUTES:
            proposal = self.agent_provider.propose(route, request, analysis)
            self._audit(audit, "design", proposal.spec.strategy_id, "completed", f"{route} proposal created")

            issues = validate_strategy_spec(
                proposal.spec,
                parent=request.parent_spec,
                proposal=proposal,
            )
            if issues:
                errors = tuple(f"{issue.code}:{issue.path}" for issue in issues)
                candidates.append(
                    CandidateRun(
                        candidate_type=route,
                        state="rejected_by_validation",
                        proposal=proposal,
                        validation_errors=errors,
                    )
                )
                self._audit(audit, "spec_validation", proposal.spec.strategy_id, "rejected", ",".join(errors))
                continue

            risk_review = self.agent_provider.review_risk(proposal)
            if risk_review.verdict == "reject":
                candidates.append(
                    CandidateRun(
                        candidate_type=route,
                        state="rejected_by_risk",
                        proposal=proposal,
                        risk_review=risk_review,
                    )
                )
                self._audit(audit, "risk_review", proposal.spec.strategy_id, "rejected", ",".join(risk_review.reason_codes))
                continue

            code = self.code_generator.generate(proposal.spec)
            self._audit(audit, "code_generation", proposal.spec.strategy_id, "completed", code.sha256)
            code_validation = validate_generated_code(proposal.spec, code)
            attempt = 0
            while (
                not code_validation.valid
                and self.repair_provider is not None
                and attempt < request.constraints.max_repair_attempts
            ):
                attempt += 1
                code = self.repair_provider.repair(
                    RepairRequest(
                        spec=proposal.spec,
                        failed_code=code,
                        validation_errors=code_validation.errors,
                        attempt=attempt,
                    )
                )
                code_validation = validate_generated_code(proposal.spec, code)
                self._audit(
                    audit,
                    "code_repair",
                    proposal.spec.strategy_id,
                    "completed" if code_validation.valid else "failed",
                    f"attempt={attempt}; errors={','.join(code_validation.errors)}",
                )
            if not code_validation.valid:
                candidates.append(
                    CandidateRun(
                        candidate_type=route,
                        state="rejected_by_code",
                        proposal=proposal,
                        risk_review=risk_review,
                        generated_code=code,
                        code_validation=code_validation,
                    )
                )
                self._audit(
                    audit,
                    "code_validation",
                    proposal.spec.strategy_id,
                    "rejected",
                    ",".join(code_validation.errors),
                )
                continue
            backtest = self.backtest_provider.run(proposal.spec, code)
            self._audit(audit, "backtest", proposal.spec.strategy_id, backtest.status, backtest.run_id)
            decision = self.agent_provider.decide(request, proposal, backtest)
            state = "accepted" if decision.verdict == "accept" else "rejected_after_backtest"
            candidates.append(
                CandidateRun(
                    candidate_type=route,
                    state=state,
                    proposal=proposal,
                    risk_review=risk_review,
                    generated_code=code,
                    code_validation=code_validation,
                    backtest_result=backtest,
                    decision=decision,
                )
            )
            self._audit(audit, "decision", proposal.spec.strategy_id, decision.verdict, ",".join(decision.reason_codes))

        return OptimizationResult(
            optimization_id=request.optimization_id,
            status="completed",
            analysis=analysis,
            candidates=tuple(candidates),
            audit_log=tuple(audit),
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
    def _audit(
        events: list[AuditEvent],
        stage: str,
        subject_id: str,
        outcome: str,
        detail: str,
    ) -> None:
        events.append(
            AuditEvent(
                sequence=len(events) + 1,
                stage=stage,
                subject_id=subject_id,
                outcome=outcome,
                detail=detail,
            )
        )
