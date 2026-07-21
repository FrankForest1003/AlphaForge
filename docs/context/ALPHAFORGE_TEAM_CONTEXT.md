# AlphaForge Team Context

## Purpose

AlphaForge is an auditable multi-Agent research pipeline that proposes one Traditional, one ML and one Hybrid QuantConnect/LEAN candidate from an immutable parent `StrategySpec` and five normalized validation results. It is an educational research system and does not connect to live capital.

## Workflow

```text
EvidenceSummarizer
→ Strategy Designer × 3
→ deterministic SpecBuilder
→ deterministic StrategyCompiler × 3 routes
→ static source validation
→ Code Risk Agent × 3
→ LEAN smoke interface
→ backtest interface
→ one Post-Backtest Analysis Agent
→ deterministic CandidateSelector
```

The three route pipelines execute concurrently. Unified analysis begins only after all three routes have succeeded or terminated.

## Model roles

There are seven runtime prompts:

| Role | Authority |
|---|---|
| Traditional Designer | Traditional signal, lookback and optional `top_k` |
| ML Designer | Estimator, task, training window, horizon, feature version, seed and optional `top_k` |
| Hybrid Designer | Both components, fusion weight and optional `top_k` |
| Traditional Code Risk | Audit traditional source against its Spec and route checklist |
| ML Code Risk | Audit feature, label, estimator and exposure behavior |
| Hybrid Code Risk | Audit both components, common Symbol set and percentile fusion |
| Post-Backtest Analysis | Explain seven metrics, cite evidence and produce a non-binding ranking |

No model role writes or patches source code.

Each English Prompt v2 file is self-contained and has ten sections: Identity, mission, inputs, owned decisions, excluded decisions, route rules, procedure, output contract, refusal behavior and final self-check. `ContextAssembler` selects exactly one registered file; the structured client adds no hidden System-message prefix or suffix. Complete Chinese translations exist only for team review in `CURRENT_AGENT_CONTEXT.md`.

## Deterministic strategy compilation

`DeterministicStrategyCompiler` maps each supported validated Spec to versioned Traditional, ML or Hybrid template regions. The common skeleton owns:

- imports, dates, cash and Symbol registration;
- warm-up and one monthly schedule;
- completed-history reads and duplicate-rebalance protection;
- top-k selection, capped equal weights and liquidation;
- long-only and total-exposure constraints.

`qc_semantics_v1` fixes completed-bar momentum and mean reversion, the eight `price_volume_v1` features, leakage-safe historical labels, estimator/task mapping and percentile-based Hybrid fusion. Unsupported Specs or environments fail explicitly; no alternate signal or placeholder estimator is substituted.

The compiled artifact records source, Spec, template, compiler and semantics digests. Static validation runs before any model code-risk review.

## Failure behavior

- Design or Schema failure rejects the design.
- Unsupported Spec or compilation failure rejects code validation.
- Static validation failure rejects code validation.
- Any non-approved Code Risk verdict rejects code risk.
- Smoke failure rejects Smoke testing.
- A failed route is never patched or retried by a model.

Code Risk receives no performance results. It returns evidenced findings and may block execution, but it cannot mutate code or the Spec. `max_drawdown_limit` remains a post-backtest deterministic admission threshold.

## Analysis and selection

The single analysis call sees the parent, four baselines, all successful candidates and failed-route statuses. It compares CAGR, Sharpe, Sortino, maximum drawdown, annualized volatility, turnover and fees, cites run IDs and labels simulated evidence correctly. Its ranking cannot override `CandidateSelector`.

## Runtime and security

The project environment is managed by uv. The OpenAI-compatible structured client reads generic runtime configuration, sends one registered English prompt plus the target JSON Schema and dynamic input, and permits one validation-directed retry. Trace records sanitized requests, final replies, prompt identity and token/cache usage. It never records credentials or model reasoning content. `.env`, Git data, Chinese prompts and unregistered files cannot enter a context bundle.
