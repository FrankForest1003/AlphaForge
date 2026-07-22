# AlphaForge

AlphaForge is an auditable multi-Agent research pipeline for designing, validating, backtesting and comparing QuantConnect/LEAN strategies.

## Pipeline

```text
Five reference Specs + normalized validation results
→ deterministic EvidenceSummarizer
→ Traditional / ML / Hybrid Strategy Designers (parallel per round)
→ strict CandidateDesign validation
→ deterministic SpecBuilder
→ StrategySpec validation
→ semantic deduplication
→ deterministic StrategyCompiler
→ static source validation
→ route-specific Code Risk Agents
→ LEAN smoke test
→ full backtest
→ deterministic iteration stop or next-round feedback
→ one Post-Backtest Analysis Agent
→ deterministic CandidateSelector
```

Models make research judgments where explanation and semantic review are useful. They do not write or patch source code. The compiler deterministically maps every supported `StrategySpec` into versioned QC templates. A compilation, static-validation, risk-review or Smoke failure terminates that route.

The three route pipelines run concurrently inside each round. A later round receives the complete same-route attempts and results, while semantic digests prevent retesting a parent, baseline or prior candidate. Unified analysis runs once after a candidate passes deterministic admission or the configured round limit is exhausted.

## Environment

The project uses [uv](https://docs.astral.sh/uv/) with `.python-version`, `pyproject.toml` and `uv.lock`.

```bash
uv sync --dev
uv run pytest
```

Run the offline closed loop:

```bash
uv run python scripts/run_mock_optimisation.py
```

For real model-backed design, risk review and analysis with the configured Local LEAN Worker, configure the generic model variables in `.env`, configure the Worker token in `lean_worker/.env`, and run:

```bash
uv run python scripts/run_llm_optimisation.py
```

The command first compiles and backtests the parent plus four fixed baselines on the same Local LEAN environment. Designers receive the explicit admission constraints and each reference Spec together with its complete result, not merely the best metric. Candidates may change route logic, top-k, target gross exposure and an optional benchmark-SMA regime filter; hard risk policy remains immutable. It then deploys each non-duplicate digest-bound candidate, performs a Smoke Test, and runs the full validation backtest. Use `--evidence-input <validation_evidence.json>` to reuse an audited evidence set.

The demonstration request states its mandate explicitly: Sharpe must not deteriorate from the parent, maximum drawdown may deteriorate by at most two percentage points, and the absolute drawdown ceiling is 50%. These are demonstration settings, not universal investment standards.

If a versioned Worker deployment contract is corrected after it rejected otherwise validated source, `--resume-result <optimization_result.json>` replays only those exact digest-bound Smoke/backtest stages and then performs one fresh unified analysis. It never regenerates the design or bypasses a code-risk rejection.

## Documentation

- `docs/context/ALPHAFORGE_TEAM_CONTEXT.md`: project context and component boundaries.
- `docs/context/CURRENT_AGENT_CONTEXT.md`: all seven English prompts and complete Chinese translations.
- `docs/architecture/SYSTEM_ARCHITECTURE.md`: execution and trust boundaries.
- `docs/architecture/AGENT_ARCHITECTURE.md`: model roles and policies.
- `docs/api/README.md`: contracts, schemas and examples.

AlphaForge is an education and research system. It does not provide investment advice or guarantee performance.
