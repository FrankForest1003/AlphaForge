# 领域合同

## StrategySpec

`StrategySpec` 是策略语义的唯一规范表示。它包含 ID、父策略、候选路线、Universe、执行参数、硬风险约束和 discriminated `logic`。

固定边界：

- Universe 为 10–30 个唯一标的，并带白名单版本。
- 执行周期、初始资金、日线 Resolution 和月度调仓由父策略继承。
- `long_only=true`、`max_leverage=1.0`，单仓上限不超过 35%。
- `candidate_type` 必须与 `logic.kind` 一致。
- 非用户策略必须包含 `parent_strategy_id`。
- 日期为 ISO 8601；比例使用小数；金额单位由运行环境约定。

## EvidenceSummary 与 CandidateDesign

`EvidenceSummarizer` 确定性比较用户策略和四个基线的七项指标，记录数值、最优策略和 run ID，不调用模型。

`CandidateDesign` 仅包含：

- `candidate_type`；
- 与路线匹配的 `logic`；
- `execution_changes.top_k`；
- 空的 `risk_changes`；
- `design_reasons` 和 `expected_tradeoffs` 字符串数组。

Designer 不提供策略 ID、Universe、日期、资金、Resolution 或硬风险字段。`SpecBuilder` 从父 Spec 复制固定字段、分配 ID、应用 allowlist 修改，并用确定性 JSON diff 生成 `changed_paths`。

## GeneratedCode 与 CodeRiskReview

`GeneratedCode` 是 QC 代码产物，包含 `main.py` 源码、策略 ID、Spec SHA-256、源码 SHA-256、使用的 QC API、实现假设和生成元数据。

静态校验核对：

- 策略 ID、Spec 摘要和源码摘要；
- Python AST、禁止导入和越权访问模式；
- `QCAlgorithm` 子类与 `Initialize`；
- 声明和观察到的 QC API 是否在 allowlist 内；
- 明显未来数据模式。

`CodeRiskReviewRequest` 只允许携带 `StrategySpec`、生成代码、静态报告和 LEAN 环境。`CodeRiskReview` 必须绑定当前策略 ID、Spec 摘要和源码摘要；其 verdict 为 `approve`、`repair_required` 或 `reject`。阻断 finding 必须给出类别、代码位置、证据、风险及修复要求。

Repair 共用一次有限尝试计数。任何修复都必须保持 Spec 摘要不变，并重新进入静态校验与代码风险审查。

## BacktestResult 与统一分析

`BacktestResult` 是回测证据的标准形态，指标固定为 CAGR、Sharpe、Sortino、最大回撤、年化波动率、换手率和总费用。设计阶段要求恰好五个 completed 的 validation/train 结果，角色为：

```text
user, baseline_b1, baseline_b2, baseline_b3, baseline_b4
```

任何 `dataset_split="test"` 输入在设计前拒绝。

三条路线结束后只构造一次 `PostBacktestAnalysisRequest`。分析覆盖父策略、四个基线、成功候选、失败路线、Spec diff 和 run IDs。分析结果必须逐项复现输入中的七项数值；推荐仅为解释性排序。

## SelectionResult 与最终状态

`CandidateSelector` 确定性检查：路线已通过前置阶段、结果完整、Sharpe 最低改善、最大回撤相对恶化、策略回撤硬上限。分析 Agent 的推荐不能覆盖失败规则。符合规则的候选按 Sharpe、较低回撤、较低费用依次排序。

路线最终状态只有：

```text
rejected_by_design
rejected_by_spec
rejected_by_code_validation
rejected_by_code_risk
rejected_by_smoke_test
backtested_not_selected
selected
```

`OptimizationResult` 保存三条路线的阶段产物、一次统一分析、确定性选择和顺序化审计事件。没有候选通过时，`selected_strategy_id=null` 且 `no_robust_improvement=true`。

## 安全边界

- API 密钥只从 `API_KEY` 读取，不进入 Schema、日志、结果或审计记录。
- `MODEL` 与 `BASE_URL` 仅属于运行配置。
- 原始本地路径不进入传输合同。
- 模型不执行数值排序、硬风险规则或最终阈值决策。
- `CodeRiskAgent` 的请求类型中不存在任何 smoke 或回测结果字段。
