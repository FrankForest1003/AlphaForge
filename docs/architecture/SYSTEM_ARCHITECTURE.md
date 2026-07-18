# System Architecture

## Boundary view

```mermaid
flowchart TD
  WEB["Streamlit Web"] --> API["FastAPI application layer"]
  API --> SVC["Application services"]
  SVC --> ORCH["Optimisation orchestrator"]
  SVC --> BPORT["BacktestProvider port"]
  ORCH --> APORT["AgentProvider port"]
  ORCH --> VALID["Deterministic spec validator"]
  ORCH --> CPORT["CodeGenerationProvider port"]
  ORCH --> BPORT
  DSL["Future external DSL"] --> CODEC["StrategyDocumentCodec"]
  CODEC --> SPEC["Canonical StrategySpec"]
  APORT --> SPEC
  VALID --> SPEC
  CPORT --> SPEC
  BPORT --> RESULT["Standard BacktestResult"]
  RESULT --> ORCH
  LEAN["Local LEAN adapter"] -. "Phase 2" .-> BPORT
  MOCK["Mock adapters"] --> APORT
  MOCK --> BPORT
```

## Allowed dependencies

```text
Web → API → Services
Services → Orchestrator / Backtest port / Repository port
Orchestrator → ports / schemas / deterministic validators
Adapters → ports / schemas / external systems
```

Disallowed dependencies:

- UI → LEAN;
- Agent → market data directory;
- Agent → Test results;
- code generator → mutable StrategySpec;
- Repair Agent → strategy semantics;
- raw LEAN result → Web or Agent without normalisation;
- notebook → production service.

## Ownership boundaries

- Members A/B own strategy semantics and baseline code.
- Member C owns LEAN execution and raw-result normalisation.
- Member D owns Agent orchestration, codecs, deterministic policy and codegen architecture.
- Cross-module schemas require review from the producer and consumer.

## Current vertical slice

The Phase 1 vertical slice uses deterministic Agent, generator and backtest adapters. It proves object flow, route separation, policy rejection, state transitions and auditability. It does not validate strategy profitability or LEAN compatibility.
