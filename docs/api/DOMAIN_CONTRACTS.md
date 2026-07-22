# Domain Contracts

## Strategy design

`StrategySpec` is the canonical strategy definition. `CandidateDesign` owns route logic plus allowlisted `top_k`, `target_gross`, `regime_filter` and `regime_lookback_days` changes. `benchmark_sma` moves to cash when the benchmark is not above its configured moving average. `SpecBuilder` copies universe, dates, capital, resolution, rebalance protocol and hard risk fields from the parent. Unknown fields and unsupported feature versions are rejected.

`EvidenceSummary.reference_strategies` contains the parent and four baselines, each with its complete Spec, normalized result, run ID and identity-free semantic digest. `DesignRequest` also carries the exact optimization constraints; `prior_attempts` carries only the same route's earlier rounds. Semantic matches are rejected before compilation and reuse no compute.

## Context and environment

`AgentContextBundle` contains one registered English prompt file plus prompt identity, version, SHA-256 and character count. Seven prompts are registered: three design, three code-risk and one post-backtest analysis. Chinese translations are not runtime sources.

`LeanEnvironmentManifest` declares `allowed_imports`, `python_dependencies`, `qc_api_profile` and `template_compatibility` alongside LEAN, Python, data and execution identities.

## Deterministic compilation

`StrategyCompilationRequest` binds a validated Spec to its digest, environment, QC API allowlist, route template, template digest and `qc_semantics_v1`.

`GeneratedCode` stores the complete `main.py`, source and Spec digests, compiler identity/digest, template identity/digest, semantics version, generated regions, used QC APIs and assumptions. The compiler rejects unsupported inputs instead of emitting substitute logic.

## Validation and code risk

Static validation checks hashes, Python AST, imports, QC API use, lifecycle methods and obvious future-data patterns. Code Risk then checks implementation behavior without any backtest result. Its verdict never modifies source. A non-approved verdict terminates the route and records a required offline engineering correction.

The Worker validates `target_gross` as one constant in `(0, 0.95]`; the platform validator separately binds its exact value to the StrategySpec. A resume operation is limited to source that already passed static validation and Code Risk and whose Smoke failure names a corrected Worker contract. All original source and Spec digests remain unchanged.

`max_drawdown_limit` is a deterministic post-backtest admission threshold. It is not a runtime trading-stop instruction and is excluded from the executable-semantic digest.

## Analysis and selection

Post-Backtest Analysis compares the user strategy, four baselines and successful candidates using seven fixed metrics and exact run IDs. Its ranking is explanatory. `CandidateSelector` independently enforces pipeline completion, result completeness, Sharpe improvement and drawdown constraints. The demonstration mandate explicitly uses zero minimum Sharpe deterioration, at most two percentage points of drawdown deterioration, and a 50% absolute drawdown ceiling; production callers must supply their own mandate rather than inherit the demonstration values.

## Security

The model client reads only generic runtime configuration. Credentials, `.env`, Git data, unregistered files and test-set tuning evidence cannot enter model requests, schemas, results or audit records.
