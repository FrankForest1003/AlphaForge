# AlphaForge Repository Layout

The repository is a monorepo containing the platform and the isolated Local LEAN Runtime v1.1.3.

## Key boundaries

- `frontend/`: Streamlit presentation layer only.
- `backend/`: FastAPI application, job orchestration, persistence, and public API.
- `agent/`: multi-agent orchestration and structured agent outputs.
- `strategy_engine/`: AlphaForge DSL, validators, capability registry, and DSL-to-QC compiler.
- `qc_strategies/`: reviewed baselines, smoke strategies and non-runtime fixtures.
- `shared/contracts/`: cross-module JSON Schema contracts; freeze these before parallel implementation.
- `lean_worker/`: isolated Local LEAN runtime and HTTP worker. Its market data, jobs, results, models, locks, and backups remain ignored by its own `.gitignore`.
- `experiments/`: reproducible manifests and small reports; large generated artifacts should not be committed.
- `docs/`: architecture, API, research, data, governance, UX, decisions, and current team context.

## Strategy source rule

`StrategySpec` is the semantic source of truth for generated candidates. `strategy_engine/` deterministically compiles it into a digest-bound source artifact. The backend deploys that artifact through `POST /v1/strategies/generated`; the Worker stores its runtime copy under the ignored generated workspace. Reviewed baselines under `qc_strategies/` remain ordinary team-owned source.

## Execution path

```text
Backend orchestration
→ Agent research judgments
→ Strategy Engine compilation and validation
→ authenticated Local LEAN Worker deployment
→ Smoke Test and full backtest
→ normalized evidence and deterministic selection
```
