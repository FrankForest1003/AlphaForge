# Agent Architecture

AlphaForge has seven runtime model roles:

| Role | Instances | Output | Authority |
|---|---:|---|---|
| Strategy Designer | 3 per round | `CandidateDesign` | Propose non-duplicate route logic, breadth, exposure and optional benchmark regime control |
| Code Risk | 3 | `CodeRiskReview` | Audit deterministic code against its Spec and implementation-risk checklist |
| Post-Backtest Analysis | 1 | `PostBacktestAnalysis` | Compare normalized evidence and provide a non-binding ranking |

Source code is produced by `DeterministicStrategyCompiler`, which is a normal Python component rather than a model role.

## Interfaces

```text
StrategyDesigner.design(DesignRequest) → CandidateDesign
StrategyCompiler.compile(StrategyCompilationRequest) → GeneratedCode
CodeRiskAgent.review(CodeRiskReviewRequest) → CodeRiskReview
PostBacktestAnalysisAgent.analyze(PostBacktestAnalysisRequest) → PostBacktestAnalysis
```

## Prompt routing

| Role | Traditional | ML | Hybrid |
|---|---|---|---|
| Strategy Designer | `strategy_designer_traditional_v2` | `strategy_designer_ml_v2` | `strategy_designer_hybrid_v2` |
| Code Risk | `code_risk_traditional_v2` | `code_risk_ml_v2` | `code_risk_hybrid_v2` |
| Post-Backtest Analysis | `post_backtest_analysis_v2` | `post_backtest_analysis_v2` | `post_backtest_analysis_v2` |

Each System message is exactly one registered English prompt file. Chinese translations are human-review documents and never enter requests.

## Code Risk boundary

`CodeRiskReviewRequest` contains only `StrategySpec`, `GeneratedCode`, `CodeValidationResult` and `LeanEnvironmentManifest`. It has no result-series or performance-metric field. Findings require a code location, concrete evidence, risk statement and required engineering correction.

An `approve` verdict permits Smoke testing. Any other verdict terminates the route. The audit recommendation cannot mutate the Spec, compiler output or template.

## Analysis boundary

One analysis call compares the parent, four baselines and every successful candidate across CAGR, Sharpe, Sortino, maximum drawdown, annualized volatility, turnover and fees. It cites run IDs and identifies mock or simulated evidence. `CandidateSelector` independently enforces the deterministic admission rules.

## Iteration boundary

Every Designer receives the explicit optimization constraints, five complete reference Specs and normalized results. Round two or three additionally receives only its own route's prior Specs, states and results. A deterministic semantic digest ignores strategy identity, lineage and the non-executable post-backtest drawdown threshold; a match against any reference or prior attempt is recorded as `duplicate_of_reference` and is not compiled or backtested. Iteration stops as soon as deterministic admission finds an eligible candidate or when `max_rounds` is exhausted.

A continuation may allocate its next-round budget to a registered subset of routes. Earlier outcomes remain in unified analysis and deterministic selection. Route allocation changes research compute only; it cannot alter admission thresholds or make an untested candidate eligible.

## Model policies

| Operation | Reasoning effort | Output ceiling |
|---|---:|---:|
| Strategy design | high | 6,000 |
| Code risk review | high | 10,000 |
| Post-backtest analysis | high | 16,000 |

Thinking-enabled requests use only the provider-native `high` and `max` values. Compatibility aliases such as `medium` are rejected locally instead of being silently mapped.

Every response must satisfy its Pydantic schema. One validation-directed retry is allowed. Traces store sanitized requests and final structured replies, but not credentials or reasoning content.
