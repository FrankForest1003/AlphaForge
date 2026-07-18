# AlphaForge Interface Documents

This directory defines the seams between the four workstreams. The purpose is to let Traditional, ML, LEAN and Agent work progress without importing one another's implementation details.

## Source-of-truth order

1. Pydantic models under `src/alphaforge/schemas/` are the executable domain contract.
2. Protocols in `src/alphaforge/ports.py` are the Python component contract.
3. Generated JSON Schemas under `docs/api/schemas/` are exchange/validation artefacts.
4. `openapi.yaml` is the transport contract draft.
5. Examples and prose explain intent but do not override executable schemas.

When a contract changes, update the Pydantic model, tests, generated JSON Schema, OpenAPI document and example in the same pull request.

## Interface map

| Producer | Consumer | Contract | Owner / reviewers | Phase 1 implementation |
|---|---|---|---|---|
| Member A/B strategy code | Member C LEAN worker | Strategy Manifest + QC `main.py` | A/B + C | documented only |
| Member C result parser | Member D Agent layer | `BacktestResult` | C + D | Pydantic + fixture |
| Agent provider | Orchestrator | `AgentProvider` | D | deterministic mock |
| Orchestrator | Spec validator | `StrategySpec` + `CandidateProposal` | all members | implemented |
| Validated spec | Code generator | `StrategySpec → GeneratedCode` | D + C | deterministic placeholder |
| Code generator | Backtest provider | `GeneratedCode` + `StrategySpec` | D + C | mock provider |
| Backtest provider | Decision Agent | `BacktestResult` | C + D | mock provider |
| Web client | Application service | HTTP `/v1/*` | later integration owner | OpenAPI draft only |

## Documents

- `DOMAIN_CONTRACTS.md`: invariants and field semantics.
- `PYTHON_PORTS.md`: provider protocols and dependency direction.
- `HTTP_API.md`: transport behaviour, async jobs and error format.
- `openapi.yaml`: machine-readable HTTP draft.
- `schemas/`: generated JSON Schema snapshots.

## Compatibility policy

- `0.1-draft` is intentionally unstable while Phase 1 validates the four baselines.
- Additive optional fields are allowed within `0.1-draft`.
- Renames, removals, changed units or semantic changes require a Decision Log entry and a schema-version bump.
- The final external DSL must be introduced as a new `StrategyDocumentCodec`; it must not leak into Agent or LEAN provider interfaces.
- Unknown fields are rejected (`extra="forbid"`) so cross-team drift fails early.
