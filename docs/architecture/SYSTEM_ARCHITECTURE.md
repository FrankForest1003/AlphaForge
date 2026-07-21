# System Architecture

```mermaid
flowchart TD
  INPUT["Parent Spec + baseline definitions"] --> EVIDENCE["Local LEAN ValidationEvidenceRunner"]
  EVIDENCE --> SUMMARY["EvidenceSummarizer"]
  SUMMARY --> DESIGN["Three Strategy Designers"]
  DESIGN --> SPEC["SpecBuilder + Spec validation"]
  SPEC --> COMPILE["Deterministic StrategyCompiler"]
  COMPILE --> STATIC["Static Code Validator"]
  STATIC --> RISK["Three route-specific Code Risk Agents"]
  RISK -->|approve| DEPLOY["Worker digest-bound deployment"]
  DEPLOY --> SMOKE["Local LEAN Smoke Test"]
  SMOKE --> FULL["Local LEAN full backtest"]
  FULL --> ANALYSIS["Unified Post-Backtest Analysis"]
  ANALYSIS --> SELECT["Deterministic CandidateSelector"]
  SELECT --> RESULT["OptimizationResult"]
```

The parent and four baselines are first executed under one Local LEAN contract; their normalized results form the design evidence. Traditional, ML and Hybrid pipelines then execute in a fixed three-worker pool through code-risk review. The Local LEAN Worker serializes actual LEAN jobs through one FIFO executor because the engine configuration and licensed data are shared. Each route terminates immediately on Spec, compilation, static validation, Code Risk, Smoke or full-backtest failure. All three outcomes are joined before the single analysis request is built.

## Dependency direction

```text
entrypoints → orchestrator → ports, schemas, deterministic services
model adapters → structured client, context assembler, schemas
strategy compiler → template renderer, StrategySpec
schemas → Pydantic
```

## Trust boundaries

- `SpecBuilder` is the only component that constructs candidate Specs.
- `DeterministicStrategyCompiler` is the only runtime component that produces strategy source.
- Lifecycle, scheduling, liquidation, position caps and route semantics are versioned code, not model output.
- Generated source binds the exact Spec, template, semantics and compiler digests.
- Static validation checks syntax, imports, QC API use, lifecycle methods and obvious lookahead patterns.
- Code Risk can block a route but cannot edit source or receive backtest results.
- Post-backtest analysis can explain and rank evidence but cannot override selection rules.
- Context bundles can read only registered English prompt files.
- Credentials and provider configuration remain runtime-only.
- Worker deployment validates the source and Spec digests before accepting a generated strategy.
- Only completed, data-complete Worker results can enter deterministic selection.

`LeanEnvironmentManifest` declares the target environment, allowed imports, Python dependencies, QC API profile and compatible templates. Unsupported combinations fail compilation explicitly; the compiler never substitutes another strategy.
