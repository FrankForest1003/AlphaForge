# AlphaForge Repository Structure

## Selected layout

The repository is a monorepo containing the platform and the isolated LEAN worker:

```text
NUS_AI-ML-Finance_Final_Project/
├─ frontend/                 # Streamlit UI
├─ backend/                  # FastAPI platform service
├─ agent/                    # Multi-agent orchestration
├─ strategy_engine/          # DSL, validation, compiler
├─ qc_strategies/            # Team strategy source
├─ shared/                   # Contracts and enums
├─ lean_worker/              # Local LEAN Runtime v1.1.3
├─ configs/                  # Versioned standard experiment config
├─ data_catalog/             # Metadata only, never licensed market data
├─ experiments/              # Small manifests/reports
├─ docs/                     # Project documentation and ADRs
├─ showcase/                 # Poster/demo assets
├─ scripts/                  # Repository-level utilities
└─ tests/                    # Cross-module tests
```

## Dependency direction

```text
Frontend -> Backend -> Services
Services -> Agent / Strategy Engine / LEAN Worker Client / Evaluation
Agent -> Shared Contracts + normalized evidence
Strategy Engine -> validated DSL + deterministic compiler templates
Backend -> LEAN Worker HTTP API
LEAN Worker -> LEAN engine + local licensed data
```

Forbidden shortcuts:

- Frontend must not launch LEAN directly.
- Agent free text must not enter LEAN directly.
- Runtime model output must not write or patch strategy source.
- Large market data and generated run artifacts must not be committed.
- Test data must not be exposed to optimization agents.

## Worker placement decision

The uploaded runtime is kept intact under `lean_worker/` because it already has its own Docker image, FastAPI service, registry, workspace isolation, result parser, data policy, tests, and package validation. Keeping this boundary minimizes accidental coupling and makes future extraction into a separate deployment/repository straightforward.
