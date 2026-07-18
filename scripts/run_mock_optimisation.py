#!/usr/bin/env python3
from __future__ import annotations

import json

from alphaforge.agents.orchestrator import OptimisationOrchestrator
from alphaforge.agents.providers.mock import (
    MockBacktestProvider,
    MockCodeRiskAgent,
    MockPostBacktestAnalysisAgent,
    MockQCCodeAgent,
    MockRepairAgent,
    MockStrategyDesigner,
)
from alphaforge.demo import build_demo_environment, build_demo_request


def main() -> None:
    orchestrator = OptimisationOrchestrator(
        designer=MockStrategyDesigner(),
        qc_code_agent=MockQCCodeAgent(),
        code_risk_agent=MockCodeRiskAgent(),
        repair_agent=MockRepairAgent(),
        backtest_provider=MockBacktestProvider(),
        analysis_agent=MockPostBacktestAnalysisAgent(),
        lean_environment=build_demo_environment(),
    )
    result = orchestrator.run(build_demo_request())
    print(
        json.dumps(
            {
                "optimization_id": result.optimization_id,
                "status": result.status,
                "selected_strategy_id": result.selection.selected_strategy_id,
                "candidate_states": {
                    candidate.candidate_type: candidate.state for candidate in result.candidates
                },
                "analysis_completed": result.post_backtest_analysis is not None,
                "audit_event_count": len(result.audit_log),
                "warning": "All backtest results are deterministic fixtures.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
