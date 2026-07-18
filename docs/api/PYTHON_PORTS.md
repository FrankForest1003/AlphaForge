# Python 组件端口

所有可替换组件以 `typing.Protocol` 定义在 `src/alphaforge/ports.py`。编排器只依赖端口和 Schema。

## StrategyDesigner

```python
design(DesignRequest) -> CandidateDesign
```

同一接口分别执行 traditional、ml、hybrid 路线。输入包含父 Spec 和确定性指标摘要；输出不包含父策略固定字段。

## QCCodeAgent

```python
generate(QCCodeGenerationRequest) -> GeneratedCode
```

请求包含完整 `StrategySpec`、Spec 摘要、LEAN 环境、QC API allowlist 和模板版本。输出源码及可审计摘要。

## CodeRiskAgent

```python
review(CodeRiskReviewRequest) -> CodeRiskReview
```

该请求类型只包含 Spec、代码、静态校验报告和 LEAN 环境。它检查实现偏离、订单生命周期、指标 readiness、未来数据、训练泄漏和异常敞口，不能接收回测表现。

## RepairAgent

```python
repair(RepairRequest) -> GeneratedCode
```

请求包含不可变 Spec、失败代码、失败来源、诊断和尝试次数。输出必须保持 Spec 摘要不变；编排器随后重新执行静态校验和代码风险审查。

## BacktestProvider

```python
smoke_test(StrategySpec, GeneratedCode) -> SmokeTestResult
run(StrategySpec, GeneratedCode) -> BacktestResult
```

Smoke Test 仅在静态校验和代码风险批准后执行；完整回测仅在 Smoke 通过后执行。Mock Provider 用于离线集成测试，真实 LEAN Provider 实现相同端口。

## PostBacktestAnalysisAgent

```python
analyze(PostBacktestAnalysisRequest) -> PostBacktestAnalysis
```

三条路线全部完成或终止后调用一次。输出横向指标比较、候选优缺点、trade-off、run ID 证据和非约束性排序。

## 确定性服务

以下组件不调用模型：

- `EvidenceSummarizer`：标准化五组证据。
- `SpecBuilder`：构造候选 Spec 与 diff。
- `validate_strategy_spec`：校验冻结字段和修改范围。
- `validate_generated_code`：静态代码校验。
- `validate_post_backtest_analysis`：核对分析中的数值和证据引用。
- `CandidateSelector`：执行硬规则和最终选择。

## 依赖方向

```text
orchestrator → ports + schemas + deterministic services
provider adapters → ports + schemas
schemas → Pydantic
```

Schema 包不得导入 Provider；风险审查不得导入或接收 `BacktestResult`。
