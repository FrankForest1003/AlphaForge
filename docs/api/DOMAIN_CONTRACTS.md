# Domain Contracts

## StrategySpec

`StrategySpec` is the canonical in-process representation of strategy meaning. It is not a promise that the final team DSL will use the same JSON shape.

Frozen Phase 1 invariants:

- daily resolution, monthly rebalance, long-only, no leverage;
- 10–30 unique symbols from a versioned whitelist;
- maximum position weight at most 35%;
- a candidate cannot change the parent universe or comparison period;
- `candidate_type` and discriminated `logic.kind` must agree;
- traditional, ML and hybrid logic are distinct variants;
- every non-user candidate has a `parent_strategy_id`.

The model rejects unknown fields. Dates use ISO 8601 and ratios are decimals (`0.20`, not `20`). Monetary values are USD in the Phase 1 fixtures.

## StrategyManifest and LeanEnvironmentManifest

`StrategyManifest` locates a strategy's code/spec, declares its family, symbols source, data and Python dependencies, and records a random seed where applicable. It contains metadata, not strategy meaning.

`LeanEnvironmentManifest` records the provider and versioned execution assumptions: LEAN/Python/data versions, normalization, brokerage, fees, slippage and time zone. OPEN project decisions remain explicit strings rather than being silently assigned defaults.

`BacktestSubmission` binds both manifests to a canonical `StrategySpec` and an opaque `code_artifact_id`. It never contains a developer's absolute path.

## BacktestResult

`BacktestResult` is the only evidence shape the Agent layer reads. Member C's LEAN parser is responsible for converting raw engine output into this model.

Required metrics are CAGR, Sharpe, Sortino, maximum drawdown, annual volatility, turnover and total fees. The optimisation orchestrator only accepts five completed inputs with roles:

```text
user, baseline_b1, baseline_b2, baseline_b3, baseline_b4
```

Any `dataset_split="test"` input is rejected before Agent analysis. This is a hard anti-leakage boundary.

## CandidateProposal

The Agent provider emits a complete candidate spec plus:

- declared changed JSON-pointer paths;
- concise design reasons;
- expected trade-offs.

The deterministic validator checks both the final spec and the declared mutation scope. Phase 1 candidates may only change candidate route, strategy logic, top-k and selected risk limits. They may not change the universe or backtest period.

## GeneratedCode

`GeneratedCode` contains the source, generator identity and SHA-256 digest. A code generator receives only a validated spec. It cannot return a mutated spec.

The current generator produces valid Python solely to exercise the boundary. Its output is explicitly not production LEAN code.

## OptimizationResult

Each of the three routes ends in one of four states:

```text
accepted
rejected_by_validation
rejected_by_risk
rejected_by_code
rejected_after_backtest
```

An append-only audit log records stage, subject, outcome and detail. A completed optimisation may legitimately have zero accepted candidates.

## Error taxonomy

| Code | Boundary | Meaning |
|---|---|---|
| `INVALID_SCHEMA` | transport/model | document cannot be parsed as the versioned schema |
| `EVIDENCE_SET_MISMATCH` | orchestrator | one of the five required roles is absent or duplicated |
| `TEST_EVIDENCE_FORBIDDEN` | orchestrator | held-out Test data reached optimisation |
| `UNIVERSE_CHANGE_FORBIDDEN` | spec validator | Agent changed the approved stock universe |
| `PERIOD_CHANGE_FORBIDDEN` | spec validator | Agent changed the comparison period |
| `CHANGE_SCOPE_FORBIDDEN` | spec validator | proposal declares an unapproved mutation |
| `POSITION_CAP_EXCEEDED` | risk reviewer | maximum position exceeds 35% |
| `PROVIDER_FAILURE` | provider adapter | LLM, generator or backtest provider failed |
| `SEMANTIC_REPAIR_FORBIDDEN` | repair boundary | a repair attempt changes strategy meaning |
