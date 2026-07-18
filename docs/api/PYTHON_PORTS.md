# Python Component Ports

All ports are defined as `typing.Protocol` in `src/alphaforge/ports.py`; orchestration depends on these ports, not concrete providers.

## AgentProvider

```python
analyze(OptimizationRequest) -> BaselineAnalysis
propose(route, OptimizationRequest, BaselineAnalysis) -> CandidateProposal
review_risk(CandidateProposal) -> RiskReview
decide(OptimizationRequest, CandidateProposal, BacktestResult) -> CandidateDecision
```

The provider may be deterministic, LLM-backed or recorded/replayed. It never runs LEAN, writes market data or receives Test metrics.

## CodeGenerationProvider

```python
generate(StrategySpec) -> GeneratedCode
```

Input must already have passed deterministic validation and risk review. Future Repair support should use a separate port containing the original spec, prior code and real error log. A repair output must preserve the input spec digest.

## RepairProvider

```python
repair(RepairRequest) -> GeneratedCode
```

`RepairRequest` contains the immutable spec, failed code, deterministic validation errors and bounded attempt number. The repaired artefact is rejected unless its `spec_sha256` still matches the input spec. Phase 1's deterministic repair provider simply regenerates from that spec.

## BacktestProvider

```python
run(StrategySpec, GeneratedCode) -> BacktestResult
```

`MockBacktestProvider` proves orchestration only. `LocalLeanProvider` will become the MVP adapter. A possible QuantConnect cloud adapter is non-blocking and must return the same `BacktestResult` contract.

## StrategyDocumentCodec

```python
decode(external_document) -> StrategySpec
encode(StrategySpec) -> external_document
```

This isolates the undecided DSL. `CanonicalJsonCodec` currently performs a typed JSON round trip. When the DSL is frozen, only a new codec and its conformance tests should be needed; Agent, codegen and backtest ports remain unchanged.

## Dependency rule

```text
orchestrator → ports + schemas + deterministic validator
provider adapters → ports + schemas
DSL codecs → schemas
schemas → Pydantic only
```

No provider implementation may be imported by the schemas package.
