# AlphaForge Team Context

## Purpose

AlphaForge is an auditable multi-Agent research platform that proposes one Traditional, one ML and one Hybrid candidate from an immutable parent strategy and normalized validation evidence. Every candidate is compiled deterministically, executed in the isolated Local LEAN Runtime and compared under one reproducible protocol. The platform is for education and research; it does not connect to live capital or provide investment advice.

## Repository boundaries

```text
frontend/         presentation only
backend/          public API, orchestration services and persistence
agent/            model roles, prompts and structured model adapters
strategy_engine/  DSL, validation and deterministic DSL-to-QC compilation
qc_strategies/    team-owned strategy source and generated deployment artifacts
shared/           cross-module contracts and enums
lean_worker/      isolated Local LEAN Runtime and HTTP worker
experiments/      reproducible manifests and small reports
docs/             current architecture, API and research documentation
```

Dependency direction:

```text
Frontend → Backend → Services
Services → Agent / Strategy Engine / LEAN Worker Client / Evaluation
Agent → Shared Contracts + normalized evidence
Strategy Engine → validated DSL + deterministic templates
Backend → LEAN Worker HTTP API
LEAN Worker → LEAN Engine + local licensed data
```

Free-form model text never enters LEAN. Licensed market data, runtime jobs, results, models and secrets remain outside Git.

## Optimization workflow

```text
EvidenceSummarizer
→ Strategy Designer × 3
→ deterministic SpecBuilder
→ deterministic StrategyCompiler × 3 routes
→ static source validation
→ Code Risk Agent × 3
→ Local LEAN Smoke Test
→ Local LEAN full backtest
→ one Post-Backtest Analysis Agent
→ deterministic CandidateSelector
```

Before `EvidenceSummarizer`, `ValidationEvidenceRunner` deterministically compiles and executes the parent strategy and four fixed baselines under the same Local LEAN data version, Universe, dates, capital and result parser. Fixture and Local LEAN results must never be mixed in one optimization. A validated five-result evidence artifact may be reused explicitly to avoid rerunning unchanged baselines.

Traditional, ML and Hybrid routes execute concurrently until they reach the Worker. The Worker uses a FIFO single executor because LEAN Launcher configuration and licensed data are shared resources. Unified analysis starts only after every route has completed or terminated.

## Model roles

There are seven runtime model roles:

| Role | Authority |
|---|---|
| Traditional Designer | Traditional signal, lookback and allowed execution changes |
| ML Designer | Estimator, task, training window, horizon, feature version and seed |
| Hybrid Designer | Traditional component, ML component and fusion weight |
| Traditional Code Risk | Audit deterministic traditional code against its Spec and runtime contract |
| ML Code Risk | Audit features, labels, estimator, data timing and exposure behavior |
| Hybrid Code Risk | Audit both components, common Symbol set and percentile fusion |
| Post-Backtest Analysis | Explain normalized evidence and provide a non-binding ranking |

No model role writes, rewrites or patches source code. A failed design, compilation, static check, code-risk review or Smoke Test terminates that route. Required engineering corrections are recorded for offline changes to the DSL, compiler or templates.

Each English Prompt is a self-contained physical file. `ContextAssembler` selects exactly one registered file, and the structured client adds no hidden System-message prefix or suffix. Chinese translations exist only for team review.

## Deterministic strategy compilation

`StrategySpec` is the semantic source of truth. `SpecBuilder` copies fixed universe, dates, capital, resolution and hard risk policy from the parent and applies only allowlisted candidate changes. `DeterministicStrategyCompiler` maps a validated Spec to versioned QC source. It never substitutes a different signal or estimator.

The Local LEAN Runtime contract requires:

- LEAN Engine 2.5 and Python 3.11 on `linux/amd64`;
- US Equity, Daily resolution, long-only and no leverage;
- RAW Tiingo-adjusted OHLCV stored in LEAN daily data;
- no internet, subprocess or package installation from strategy code;
- staged sell/reduce-before-buy execution;
- `target_gross <= 0.95`, `max_position_weight <= 0.35` and cash reserve;
- safe handling of missing symbols, unequal listing histories and incomplete data;
- JSON-native diagnostics and an exact completion marker;
- walk-forward ML with fully realized labels and fixed random seeds.

Compiled artifacts bind the exact Spec, source, template, compiler and semantics digests. Static validation runs before code-risk review.

## Local LEAN Worker

The Worker is isolated under `lean_worker/` and exposes HTTP on `127.0.0.1:18081`. Requests other than `/health` require `X-Worker-Token`. Jobs are submitted through `POST /v1/jobs`, polled through `GET /v1/jobs/{run_id}`, and read through `GET /v1/jobs/{run_id}/result`.

Only `completed` results with `evaluation.eligible_for_comparison=true` may enter evidence analysis. `completed_with_data_gaps`, `failed` and `timeout` remain auditable route outcomes but are not eligible for selection.

`StrategySpec` is the semantic source of truth for generated candidates. The backend submits the compiled source, source digest, Spec digest, algorithm class and completion marker through `POST /v1/strategies/generated`. The Worker validates the runtime contract and keeps the deployed copy in its ignored generated workspace. `qc_strategies/` contains reviewed baselines, smoke strategies and fixtures rather than a second copy of generated candidates.

## Code-risk evidence rules

Code Risk receives `StrategySpec`, compiled source, static-validation results and the runtime manifest. It never receives backtest performance.

Before declaring lookahead or ML leakage, the auditor must trace the complete data path in execution order: index direction, shift semantics, NaN creation, stack/unstack behavior, join alignment, drop/filter operations, final sample dates and the prediction timestamp. A blocking finding must identify at least one concrete sample whose feature or label would be unavailable at prediction time. If downstream filtering removes every incomplete label, the auditor must not report leakage for those rows.

`max_drawdown_limit` is a post-backtest deterministic admission threshold, not a runtime stop rule.

## Analysis and selection

One analysis call compares the user strategy, four baselines and every eligible candidate using CAGR, Sharpe, Sortino, maximum drawdown, annualized volatility, turnover and fees. It cites exact run IDs, labels simulated or incomplete evidence and explains failed routes. Its recommendation cannot override `CandidateSelector`.

## Runtime and security

The platform Python environment is managed by uv. Model configuration uses generic runtime variables. Worker configuration uses a separate local token and local-only endpoint. Traces never record credentials or model reasoning content. `.env`, Git data, licensed market data, Chinese prompts and unregistered files cannot enter model context.
