# AlphaForge

AlphaForge is a risk-aware multi-agent research platform that converts evidence from standardised backtests into three candidate strategy routes: traditional, machine learning, and hybrid. Strategy semantics are represented by a canonical typed model; generated LEAN code is an execution artefact, not the source of truth.

This repository currently contains the Phase 1 Agent architecture and a deterministic mock vertical slice. It deliberately does **not** claim to run QuantConnect LEAN yet and does not use test-set evidence for optimisation.

## Quick start

```bash
conda run -n ml_env python -m pip install -e '.[dev]'
conda run -n ml_env python scripts/run_mock_optimisation.py
conda run -n ml_env pytest
```

The mock run exercises:

```text
5 validation backtest results
→ baseline analysis
→ traditional / ML / hybrid proposals
→ deterministic spec validation
→ risk review
→ deterministic code artefact generation
→ mock backtest provider
→ accept/reject decisions and audit trail
```

## Start here

- `docs/context/ALPHAFORGE_TEAM_CONTEXT.md`: current frozen and open project decisions.
- `docs/api/README.md`: interface-document index and stability rules.
- `docs/architecture/SYSTEM_ARCHITECTURE.md`: dependency boundaries.
- `docs/architecture/AGENT_ARCHITECTURE.md`: Agent state machine and mock scope.
- `docs/decisions/ADR-0001-DRAFT-CANONICAL-SPEC-BOUNDARY.md`: how work continues before the final DSL is frozen.

## Current limits

- All Agent and backtest behaviour is deterministic and local.
- Generated Python is an auditable placeholder, not LEAN-compatible production code.
- The HTTP API is a contract draft; no FastAPI transport is implemented yet.
- No market data, API key, model binary, or investment advice is included.
