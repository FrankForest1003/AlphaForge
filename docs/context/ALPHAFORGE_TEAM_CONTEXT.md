# AlphaForge Team Context

## Purpose

AlphaForge is a risk-aware multi-agent platform for controlled trading-strategy research. It creates one Traditional, one ML and one Hybrid candidate from a user strategy and standardized validation evidence, produces QuantConnect/LEAN-compatible Python, performs code-risk review before backtesting, runs candidates under a common execution protocol and compares all completed results together.

The system is designed for education, research and decision support. It does not connect to live capital, guarantee returns or provide investment advice.

## End-to-end workflow

```text
User StrategySpec + S_user/B1/B2/B3/B4 validation results
→ EvidenceSummarizer
→ three Strategy Designer calls
→ CandidateDesign Schema
→ SpecBuilder
→ StrategySpec validation
→ QC Code Agent
→ deterministic static validation
→ Code Risk Agent
→ bounded Repair loop when required
→ LEAN smoke test
→ full LEAN backtest
→ one Post-Backtest Analysis Agent call
→ deterministic CandidateSelector
→ OptimizationResult and audit trail
```

## Strategy routes

| Route | Required signal structure |
|---|---|
| Traditional | Technical or statistical signal only |
| ML | Model prediction signal only |
| Hybrid | Explicit Traditional and ML components plus fusion weight |

The three routes use the same universe, dates, capital, resolution, rebalance protocol, fees, slippage, data version and benchmark assumptions.

## Agent responsibilities

### Strategy Designer

Receives a parent StrategySpec and deterministic evidence summary. Returns a strict `CandidateDesign` containing route-specific logic, permitted execution changes, design reasons and expected trade-offs.

It cannot assign IDs or change the universe, comparison period, capital, resolution or hard risk policy.

### QC Code Agent

Receives an immutable StrategySpec, its digest, the LEAN environment and QC API allowlist. Returns `main.py`, source digest, Spec digest, used APIs, implementation assumptions and generator metadata.

It translates strategy semantics into code and cannot modify the StrategySpec.

### Code Risk Agent

Runs after code generation and deterministic static validation, before smoke or full backtesting. It receives no backtest metrics.

It reviews code for implementation defects that can create excessive or unnecessary risk, including Spec drift, position sizing errors, duplicate orders, missing liquidation, indicator readiness, look-ahead, ML leakage, unintended exposure and execution mistakes.

It returns `approve`, `repair_required` or `reject`. Blocking repairable findings enter the bounded Repair loop.

### Repair Agent

Receives the immutable StrategySpec, failed code, LEAN environment, failure source, diagnostics and attempt number. It may fix implementation defects only. The Spec digest must remain unchanged.

### Post-Backtest Analysis Agent

Runs exactly once after all three routes have completed or terminated. It receives normalized parent, baseline and successful candidate results plus failed-route states and run IDs.

It compares CAGR, Sharpe, Sortino, maximum drawdown, annualized volatility, turnover and fees; explains strengths, weaknesses and trade-offs; and provides a non-binding ranking. It does not determine final eligibility.

## Deterministic services

| Service | Responsibility |
|---|---|
| EvidenceSummarizer | Calculate metric leaders and user gaps from five validation results |
| SpecBuilder | Merge permitted CandidateDesign fields into the parent StrategySpec |
| StrategySpec Validator | Enforce route, scope, universe, protocol and hard-risk invariants |
| Static Code Validator | Check syntax, hashes, imports, QC API allowlist, lifecycle methods and obvious prohibited patterns |
| Analysis Validator | Verify all seven reported metrics, strategy IDs and run IDs against supplied results |
| CandidateSelector | Enforce pipeline eligibility, result completeness, Sharpe and drawdown rules |

Deterministic services do not call a language model.

## Core contracts

### CandidateDesign

Contains `candidate_type`, route-specific `logic`, `execution_changes`, empty `risk_changes`, `design_reasons` and `expected_tradeoffs`. Unknown fields and incorrect types are rejected.

### StrategySpec

The sole source of strategy meaning. It contains version, identity, parent identity, route, universe, execution protocol, hard risk policy and a discriminated Traditional/ML/Hybrid logic object.

### GeneratedCode

Contains `main.py`, strategy identity, source digest, Spec digest, used QC APIs, assumptions and generation metadata.

### CodeRiskReview

Contains reviewed strategy/source/Spec identities, verdict and structured findings with severity, category, code location, evidence, risk and repair instruction.

### BacktestResult

Contains run identity, strategy identity, role, status, data split, provider, normalized metrics and warnings. Test results are prohibited from the design stage.

### PostBacktestAnalysis

Contains cross-strategy metric analyses, candidate assessments, non-binding recommended ranking, no-improvement flag and summary.

### SelectionResult

Contains deterministic checks for every backtested candidate, eligible IDs, selected strategy ID and no-improvement flag.

## Execution and risk constraints

- Daily data and Monthly rebalance for the standard experiment.
- Long-only, no leverage and maximum 35% position weight.
- Test evidence never enters strategy design or tuning.
- Unknown Agent-output fields are rejected.
- A failed structured response receives one schema-directed correction attempt, then fails.
- CandidateDesign cannot change frozen protocol fields.
- Generated or repaired code must preserve the StrategySpec digest.
- Code Risk review must pass before smoke testing.
- Repair attempts are bounded by the OptimizationRequest.
- Final selection cannot be overridden by an Agent recommendation.
- Zero selected candidates is a valid result.

## Provider boundaries

The production Agent implementations use a generic structured model client configured by `API_KEY`, `MODEL` and `BASE_URL`. Credentials are loaded at runtime and must never appear in source, logs, results or audit events.

`BacktestProvider` exposes `smoke_test` and `run`. Local LEAN is the production execution target. Deterministic offline providers are used for tests only.

## Definition of done

A candidate route is complete only when its design is schema-valid, its StrategySpec passes deterministic validation, generated code passes static validation and Code Risk review, smoke testing passes, the full result is normalized and the route appears in the unified post-backtest analysis and deterministic selection result.
