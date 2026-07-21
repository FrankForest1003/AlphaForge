# AlphaForge Software Prototype and API

## Runtime components

```text
Frontend → Backend API → Optimization Service
                         ├─ Agent roles
                         ├─ Strategy Engine
                         ├─ Local LEAN Worker Client
                         └─ Deterministic Evaluation
```

The Agent boundary contains three Strategy Designers, three route-specific Code Risk auditors and one unified Post-Backtest Analysis role. Models return strict structured research judgments. Models do not write or patch Python source.

The Strategy Engine owns the StrategySpec schema, allowlisted mutations, deterministic compiler, Local LEAN templates and static validators. Generated source is a reproducible artifact bound to Spec, template, semantics and compiler digests.

The Local LEAN Worker is an isolated localhost service. It owns LEAN, licensed market data, execution locks, runtime job state and detailed result parsing. The platform accesses it only through its authenticated HTTP API.

## Optimization sequence

```text
parent spec and fixed baseline definitions
→ same-environment parent and four-baseline validation
→ deterministic evidence summary
→ three parallel CandidateDesign calls
→ SpecBuilder and Spec validation
→ deterministic Local LEAN compilation
→ static code validation
→ route-specific Code Risk review
→ Worker Smoke Test
→ Worker full backtest
→ normalized result eligibility
→ one post-backtest analysis call
→ deterministic selection
```

Any non-approved design, Spec, compilation, static validation, code-risk or Smoke result terminates that route. Engineering corrections are applied offline to the Strategy Engine and require a new version; there is no runtime model repair loop.

## Worker API

Base URL: `http://127.0.0.1:18081`

All endpoints except `/health` require `X-Worker-Token`.

```text
GET  /health
GET  /v1/data/status
GET  /v1/universes/default
GET  /v1/strategies
POST /v1/strategies/generated
POST /v1/jobs
GET  /v1/jobs/{run_id}
GET  /v1/jobs/{run_id}/result
GET  /v1/jobs/{run_id}/artifacts
```

Generated-strategy deployment requires source, algorithm class, completion marker, source SHA-256, Spec SHA-256, runtime parameters and required symbols. The Worker validates and stores this material under its generated runtime workspace. A job can reference the generated strategy only after deployment succeeds.

## Result eligibility

Worker terminal states are `completed`, `completed_with_data_gaps`, `failed` and `timeout`. Only `completed` results whose `evaluation.eligible_for_comparison` equals `true` are normalized into candidate evidence. Every other state remains in the audit record and is excluded from deterministic selection.

## Security boundary

- The service binds to localhost and uses a separate Worker token.
- Market data, jobs, results, models, locks and backups are ignored by Git.
- Model credentials never enter Worker requests.
- Agent free text never enters LEAN.
- Only deterministic compiled source with matching digests can be deployed.
- Strategy source has no network, subprocess or package-install authority.
