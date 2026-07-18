# AlphaForge

AlphaForge is a risk-aware multi-agent research platform for designing, generating, validating, backtesting and comparing QuantConnect/LEAN trading strategies.

## Final pipeline

```text
Five normalized validation results
→ deterministic evidence summary
→ Traditional / ML / Hybrid Strategy Designers
→ strict CandidateDesign validation
→ deterministic SpecBuilder
→ StrategySpec validation
→ QC Code Agent
→ static QC code validation
→ Code Risk Agent
→ bounded Repair Agent when required
→ LEAN smoke test
→ full backtest
→ one unified post-backtest analysis
→ deterministic candidate selection
```

The Strategy Designer controls only strategy logic and explicitly allowed execution changes. The system owns strategy IDs, universe, dates, capital, execution protocol and hard risk policy.

The Code Risk Agent reviews generated code before any backtest evidence exists. Its request type contains the StrategySpec, source code, static validation report and LEAN environment only.

The post-backtest analysis Agent compares all completed routes in one call. Final eligibility and selection remain deterministic.

## Run the offline integration loop

```bash
conda run -n ml_env python -m pip install --no-build-isolation -e '.[dev]'
conda run -n ml_env pytest
conda run -n ml_env python scripts/run_mock_optimisation.py
```

Offline adapters use deterministic fixtures and do not constitute financial evidence. A Local LEAN provider can implement the same smoke-test and full-backtest ports.

## Documentation

- `docs/context/ALPHAFORGE_TEAM_CONTEXT.md`: authoritative project context.
- `docs/architecture/SYSTEM_ARCHITECTURE.md`: system boundaries and dependency rules.
- `docs/architecture/AGENT_ARCHITECTURE.md`: Agent responsibilities and state machine.
- `docs/api/README.md`: contracts, schemas, examples and HTTP API.

AlphaForge is an education and research system. It does not provide investment advice or guarantee strategy performance.
