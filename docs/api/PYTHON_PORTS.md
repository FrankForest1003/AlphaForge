# Python Ports

The orchestrator depends on these `typing.Protocol` interfaces:

```python
StrategyDesigner.design(DesignRequest) -> CandidateDesign
StrategyCompiler.compile(StrategyCompilationRequest) -> GeneratedCode
CodeRiskAgent.review(CodeRiskReviewRequest) -> CodeRiskReview
BacktestProvider.smoke_test(StrategySpec, GeneratedCode) -> SmokeTestResult
BacktestProvider.run(StrategySpec, GeneratedCode) -> BacktestResult
PostBacktestAnalysisAgent.analyze(PostBacktestAnalysisRequest) -> PostBacktestAnalysis
```

`StrategyCompilationRequest` binds the immutable Spec and digest to the LEAN environment, QC API allowlist, template version/digest and semantics version. `StrategyCompiler` is deterministic and has no model client.

The real model adapters cover design, code-risk review and unified analysis. Deterministic mock adapters cover those same model ports for offline tests. The backtest mock is explicit test infrastructure.
