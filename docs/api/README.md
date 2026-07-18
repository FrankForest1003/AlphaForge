# AlphaForge API Contracts

本目录定义 AlphaForge 的领域、Python 组件和 HTTP 边界。

## 合同优先级

1. `src/alphaforge/schemas/`：可执行 Pydantic 合同。
2. `src/alphaforge/ports.py`：组件 Protocol。
3. `schemas/`：由 Pydantic 导出的 JSON Schema。
4. `openapi.yaml`：HTTP 传输合同。
5. `examples/`：通过 Pydantic 验证的格式化示例。

未知字段统一拒绝。模型输出必须直接满足目标 Schema；结构错误只允许携带验证错误重试一次，第二次失败即终止该阶段。

## 组件接口图

| 生产者 | 消费者 | 合同 |
|---|---|---|
| `EvidenceSummarizer` | 三个 `StrategyDesigner` | `EvidenceSummary` / `DesignRequest` |
| `StrategyDesigner` | `SpecBuilder` | `CandidateDesign` |
| `SpecBuilder` | QC 代码阶段 | `BuiltCandidate` / `StrategySpec` |
| `QCCodeAgent` | 静态校验器 | `GeneratedCode` |
| 静态校验器 | `CodeRiskAgent` | `CodeValidationResult` |
| `CodeRiskAgent` | 编排器或 `RepairAgent` | `CodeRiskReview` |
| `RepairAgent` | 静态校验器 | `GeneratedCode` |
| `BacktestProvider` | 编排器 | `SmokeTestResult` / `BacktestResult` |
| `PostBacktestAnalysisAgent` | 编排器 | `PostBacktestAnalysis` |
| `CandidateSelector` | `OptimizationResult` | `SelectionResult` |

## 更新规则

合同变更必须同时更新 Pydantic 模型、测试、JSON Schema、OpenAPI 和相应示例。Schema 使用 `1.0`；字段含义或单位变化需要提升版本。
