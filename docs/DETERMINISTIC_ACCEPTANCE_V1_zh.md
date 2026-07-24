# AlphaForge 确定性验收策略 v1

更新日期：2026-07-23

## 为什么修改

历史版本让 Acceptance Agent 同时解释证据并决定 `accept` / `revise`。这会产生两类风险：

1. 模型可能返回格式正确但语义矛盾的检查结果；
2. Provider 可能把合法结果包装在 `output`、`report` 或 `result` 中，旧接收层只读顶层字段。

此外，依靠不断追加历史异常字符串只能提高已见案例通过率，无法形成稳定的长期边界。本轮将规范不变量、运行时证据和模型建议彻底分开。

## 新的职责边界

- Designer：先返回有限选项的 `design.strategy_spec`，再实现完整 LEAN Python。
- Static Validator：确定性检查 Python、允许的 API、共享参数和轨道能力。
- LEAN Worker：执行策略并输出 evidence schema 2.0。
- Acceptance Evidence Analyst：只解释 A1–A5，并提出一个针对首个中断阶段的修复建议。
- Backend Policy：唯一有权计算 A1–A5 状态和最终 `accept` / `revise`。
- Repair：收到原始 CandidateDesign、确定性失败证据和 Agent 建议后修复完整源码。

最终报告会包含：

```json
{
  "policy_version": "deterministic-acceptance-v2",
  "decision_source": "backend_deterministic_policy",
  "agent_advisory_decision": "模型原始建议，仅供审计"
}
```

## 结构化策略规格

Designer 契约 v3 要求 `design.strategy_spec` 只使用项目支持的有限原语：

| 字段 | 允许值 |
|---|---|
| `signal_family` | `momentum`、`mean_reversion`、`trend`、`volatility` 或 `null` |
| `model_family` | `gradient_boosting`、`random_forest` 或 `null` |
| `rebalance_frequency` | `weekly`、`monthly` |
| `lookback_days` | `63`、`126`、`252` |
| `label_horizon_days` | `10`、`21` 或 `null` |
| `top_k` | 2–5 |
| `weighting` | `equal`、`inverse_volatility` |

Traditional 必须有透明信号且没有模型；ML 必须有模型且没有独立非 ML 信号；Hybrid 必须同时具备模型和透明信号。当前仍由模型生成完整 Python，后续可直接在这份稳定 spec 上增加确定性 spec→LEAN 编译器。

## Worker evidence schema 2.0

`af_rebalance_to_weights` 会先记录 `decision_targets`。Backend 使用同一决策时间上的结构化事件建立以下计数：

- `transparent_signal_event_count`
- `target_intent_event_count`
- `signal_to_target_link_count`
- `prediction_to_target_link_count`
- `hybrid_decision_link_count`
- `training_before_prediction_count`

因此，Hybrid 即使通过 momentum fallback 产生大量订单和较高 CAGR，只要没有真实训练、预测以及共同进入目标权重的证据，A2/A3 仍会失败。收益指标只用于 PK，不参与资格验收。

## A1–A5 的权威数据来源

- A1：成交、持仓快照和最大总敞口。
- A2：训练/信号、预测、目标意图和成交的结构化运行链。
- A3：按 Traditional、ML、Hybrid 轨道检查对应事件是否真正连接到目标。
- A4：受限源码契约中的时间完整性诊断，加上训练→预测或信号→目标的运行顺序。
- A5：AST 确认七项共享参数被实际读取，并检查成交股票未越过 RunSettings 白名单。

Agent 的解释可以进入 `agent_advisory`，但不能覆盖这些状态。
Backend 的 `repair_request` 现在只包含确定性首个缺失阶段；模型提出的修复猜测
单独保存在 `agent_advisory_repair_request`。Repair 能看到它，但必须以确定性事实
为准，避免未经证明的 schedule、数据或 API 猜测污染修复目标。

### v2：完整调仓和运行失败事实

v2 在原有因果链中增加 `staged_rebalance_completed_count`。只记录目标、提交订单
或产生部分成交都不再足以通过 A2；共享调仓器必须至少记录一次
`staged_rebalance_completed`。同时记录 replacement、failed 和 canceled 数量，
用于识别“信号更新太快、上一轮调仓持续被替换”的问题。

LEAN 失败时，Backend 还会从只读 details 中建立
`runtime_failure_evidence`，把失败订单关联到 OrderEvent、失败前最近组合快照和
局部原始日志。历史字符串分类继续保留为快速提示，但 Repair 不再依赖穷举错误。

## JSON 兼容

Backend 会统一解包以下形式：

```json
{"decision": "revise"}
{"output": {"decision": "revise"}}
{"report": {"decision": "revise"}}
{"result": {"decision": "revise"}}
```

因此合法嵌套响应不会再误报 `acceptance decision must be accept or revise`。

## 验证

```powershell
$env:PYTHONPATH='D:\Code\NUS_AI-ML-Finance_Final_Project\backend;D:\Code\NUS_AI-ML-Finance_Final_Project'
.\.venv\Scripts\python.exe -m pytest backend\tests -q

$env:PYTHONPATH='D:\Code\NUS_AI-ML-Finance_Final_Project\lean_worker'
.\.venv\Scripts\python.exe -m pytest lean_worker\tests -q
```

新增的关键回归测试覆盖：

- Provider 嵌套输出解包；
- LLM 的错误 revise 建议不能推翻通过的确定性证据；
- 有订单但没有 ML 训练/预测的 Hybrid fallback 必须失败；
- 共享参数必须通过真实 `_parameter` / `get_parameter` AST 调用消费。
