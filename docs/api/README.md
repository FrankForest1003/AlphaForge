# AlphaForge API Contracts

本目录定义领域模型、Python 组件接口和 HTTP 边界。

## 合同优先级

1. `src/alphaforge/schemas/`：可执行 Pydantic 合同。
2. `src/alphaforge/ports.py`：组件 Protocol。
3. `schemas/`：由 Pydantic 导出的 JSON Schema。
4. `openapi.yaml`：HTTP 传输合同。
5. `examples/`：通过 Pydantic 验证的格式化示例。

未知字段统一拒绝。模型输出必须直接满足目标 Schema；校验失败时只允许携带错误重试一次。

## 组件接口

| 生产者 | 消费者 | 合同 |
|---|---|---|
| `EvidenceSummarizer` | 三个 `StrategyDesigner` | `EvidenceSummary` / `DesignRequest` |
| `StrategyDesigner` | `SpecBuilder` | `CandidateDesign` |
| `SpecBuilder` | `StrategyCompiler` | `BuiltCandidate` / `StrategySpec` |
| `StrategyCompiler` | 静态校验器 | `StrategyCompilationRequest` / `GeneratedCode` |
| 静态校验器 | `CodeRiskAgent` | `CodeValidationResult` |
| `CodeRiskAgent` | 编排器 | `CodeRiskReview` |
| `BacktestProvider` | 编排器 | `SmokeTestResult` / `BacktestResult` |
| `PostBacktestAnalysisAgent` | 编排器 | `PostBacktestAnalysis` |
| `CandidateSelector` | `OptimizationResult` | `SelectionResult` |

`StrategyCompiler` 是确定性 Python 组件，不是模型 Agent。模型只参与策略设计、代码风险语义审计和回测后证据分析。

## 失败语义

每条路线可在设计、Spec、代码校验、代码风险或 Smoke 阶段被拒绝。系统不会让模型修改失败代码；失败原因和必要工程修正写入该路线的审计记录。全部路线结束后仍只调用一次统一分析。

合同变更必须同步更新 Pydantic 模型、测试、JSON Schema、OpenAPI 和示例。
