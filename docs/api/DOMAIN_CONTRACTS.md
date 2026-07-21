# Domain Contracts

## Strategy design

`StrategySpec` is the canonical strategy definition. `CandidateDesign` owns route logic and an optional `top_k` change. `SpecBuilder` copies universe, dates, capital, resolution, rebalance protocol and hard risk fields from the parent. Unknown fields and unsupported feature versions are rejected.

## Context and environment

`AgentContextBundle` contains one registered English prompt file plus prompt identity, version, SHA-256 and character count. Seven prompts are registered: three design, three code-risk and one post-backtest analysis. Chinese translations are not runtime sources.

`LeanEnvironmentManifest` declares `allowed_imports`, `python_dependencies`, `qc_api_profile` and `template_compatibility` alongside LEAN, Python, data and execution identities.

## Deterministic compilation

`StrategyCompilationRequest` binds a validated Spec to its digest, environment, QC API allowlist, route template, template digest and `qc_semantics_v1`.

`GeneratedCode` stores the complete `main.py`, source and Spec digests, compiler identity/digest, template identity/digest, semantics version, generated regions, used QC APIs and assumptions. The compiler rejects unsupported inputs instead of emitting substitute logic.

## Validation and code risk

Static validation checks hashes, Python AST, imports, QC API use, lifecycle methods and obvious future-data patterns. Code Risk then checks implementation behavior without any backtest result. Its verdict never modifies source. A non-approved verdict terminates the route and records a required offline engineering correction.

`max_drawdown_limit` is a deterministic post-backtest admission threshold. It is not a runtime trading-stop instruction.

## Analysis and selection

Post-Backtest Analysis compares the user strategy, four baselines and successful candidates using seven fixed metrics and exact run IDs. Its ranking is explanatory. `CandidateSelector` independently enforces pipeline completion, result completeness, Sharpe improvement and drawdown constraints.

## Security

The model client reads only generic runtime configuration. Credentials, `.env`, Git data, unregistered files and test-set tuning evidence cannot enter model requests, schemas, results or audit records.
