# AlphaForge

AlphaForge is an auditable multi-Agent research pipeline for designing, validating, backtesting and comparing QuantConnect/LEAN strategies.

## Pipeline

```text
Five normalized validation results
→ deterministic EvidenceSummarizer
→ Traditional / ML / Hybrid Strategy Designers (parallel)
→ strict CandidateDesign validation
→ deterministic SpecBuilder
→ StrategySpec validation
→ deterministic StrategyCompiler
→ static source validation
→ route-specific Code Risk Agents
→ LEAN smoke test
→ full backtest
→ one Post-Backtest Analysis Agent
→ deterministic CandidateSelector
```

Models make research judgments where explanation and semantic review are useful. They do not write or patch source code. The compiler deterministically maps every supported `StrategySpec` into versioned QC templates. A compilation, static-validation, risk-review or Smoke failure terminates that route.

The three route pipelines run concurrently. Unified analysis starts once all routes have completed or failed. The analysis ranking is explanatory; eligibility and final selection are deterministic.

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

For real model-backed design, risk review and analysis, configure the generic variables in `.env` and run:

```bash
uv run python scripts/run_llm_optimisation.py
```

The current backtest provider in that script is deterministic test infrastructure, not financial evidence. Readable traces are written under `artifacts/debug_runs/latest/` and omit credentials and model reasoning content.

## Documentation

- `docs/context/ALPHAFORGE_TEAM_CONTEXT.md`: project context and component boundaries.
- `docs/context/CURRENT_AGENT_CONTEXT.md`: all seven English prompts and complete Chinese translations.
- `docs/architecture/SYSTEM_ARCHITECTURE.md`: execution and trust boundaries.
- `docs/architecture/AGENT_ARCHITECTURE.md`: model roles and policies.
- `docs/api/README.md`: contracts, schemas and examples.

AlphaForge is an education and research system. It does not provide investment advice or guarantee performance.
