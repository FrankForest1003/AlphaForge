# ADR-0001: Use a Canonical Spec Boundary Before the DSL Is Frozen

- Status: Accepted for Phase 1; revisit when the team freezes Strategy Spec v1.
- Date: 2026-07-18.

## Context

The Agent workstream must start before the external Strategy DSL syntax and full field set are final. Binding orchestration directly to a provisional DSL would spread churn across Agent prompts, validation, code generation, LEAN execution and tests.

## Decision

Use a small, typed `StrategySpec` as the canonical in-process semantic model and place every external syntax behind `StrategyDocumentCodec`.

The temporary `CanonicalJsonCodec` is an identity adapter for JSON. Agent providers exchange typed proposals, not DSL strings. Code generators and backtest providers also consume the typed model. When the DSL is frozen, implement a new codec and conformance tests at the boundary.

The draft model covers only the Frozen Phase 1 protocol and the three candidate routes. It is not a general-purpose trading language.

## Consequences

Positive:

- the mock vertical slice runs now;
- the final DSL can change syntax without rewriting orchestration;
- validation errors are deterministic and testable;
- provider adapters are replaceable;
- semantic ownership remains explicit.

Costs and risks:

- a mapping step is required once the DSL is final;
- the draft canonical model may need a versioned migration;
- JSON round trips must be covered by conformance tests;
- the team must avoid treating `0.1-draft` as Frozen.

## Revisit criteria

Revisit after Members A/B provide four baseline specs and Member C provides a real normalised LEAN result. Freeze Strategy Spec v1 only after all four strategies can be represented without implementation-specific escape hatches.
