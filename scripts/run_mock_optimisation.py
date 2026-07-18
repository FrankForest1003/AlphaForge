#!/usr/bin/env python3
from __future__ import annotations

import json

from alphaforge.agents.orchestrator import OptimisationOrchestrator
from alphaforge.agents.providers.mock import MockAgentProvider, MockBacktestProvider
from alphaforge.codegen.generator import DeterministicCodeGenerator
from alphaforge.demo import build_demo_request


def main() -> None:
    orchestrator = OptimisationOrchestrator(
        agent_provider=MockAgentProvider(),
        code_generator=DeterministicCodeGenerator(),
        backtest_provider=MockBacktestProvider(),
    )
    result = orchestrator.run(build_demo_request())
    summary = {
        "optimization_id": result.optimization_id,
        "status": result.status,
        "accepted_types": result.accepted_types,
        "candidate_states": {
            candidate.candidate_type: candidate.state for candidate in result.candidates
        },
        "audit_event_count": len(result.audit_log),
        "warning": "All candidate results are simulated and are not financial evidence.",
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
