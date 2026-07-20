# AlphaForge Repository Overlay v0.1

This overlay prepares the top-level monorepo structure for AlphaForge and places the validated Local LEAN Runtime v1.1.3 under `lean_worker/`.

## Key boundaries

- `frontend/`: Streamlit presentation layer only.
- `backend/`: FastAPI application, job orchestration, persistence, and public API.
- `agent/`: multi-agent orchestration and structured agent outputs.
- `strategy_engine/`: AlphaForge DSL, validators, capability registry, and DSL-to-QC compiler.
- `qc_strategies/`: team-owned strategy source code and smoke strategies.
- `shared/contracts/`: cross-module JSON Schema contracts; freeze these before parallel implementation.
- `lean_worker/`: isolated Local LEAN runtime and HTTP worker. Its market data, jobs, results, models, locks, and backups remain ignored by its own `.gitignore`.
- `experiments/`: reproducible manifests and small reports; large generated artifacts should not be committed.
- `docs/`: architecture, API, research, data, governance, UX, decisions, and current team context.

## Strategy code rule

`qc_strategies/` is the team source-of-truth. `lean_worker/strategies/approved/` contains strategies deployed/approved inside the runtime. Deployment should later be automated rather than maintained as two unrelated copies.

## Current integration priority

1. Freeze shared contracts and AlphaForge DSL v1.
2. Connect backend to `lean_worker/` through its HTTP API.
3. Trigger a real smoke run and full backtest from the backend.
4. Normalize the returned result.
5. Connect the three candidate DSLs to the compiler and worker.
