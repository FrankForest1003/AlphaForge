# AlphaForge 验收职责边界（v3 迁移说明）

更新日期：2026-07-24

> 文件名为历史兼容保留。当前实现不再由 Backend 生成 A2–A4 或最终语义结论。

## 当前职责

- Designer：返回有界 `design.strategy_spec` 与完整标准生命周期 LEAN Python。
- Narrow Preflight：只检查 Python 语法和明确危险的文件、进程、网络能力。
- LEAN Worker：执行策略，并通过任务副本中的 observer 输出真实运行证据。
- Acceptance Agent：独立审核 A1–A5，输出每项 pass/fail、最终
  `accept/revise` 和一个有界 `repair_request`。
- Backend Guard：规范化 JSON 外壳、检查报告内部一致性，并用确定性事实约束
  A1 的实际投资行为和 A5 的成交白名单。
- Repair：根据 Worker 失败事实或 Acceptance revise 修改完整源码。

Backend 不使用事件计数或关键词替代 Agent 对 A2 因果链、A3 轨道完整性和 A4
时间完整性的语义审核。

## 标准生命周期与执行自主权

策略使用 `initialize`、`on_data`、`on_order_event`、
`on_end_of_algorithm`。`AlphaForgeBaseAlgorithm` 不固定 2% 现金缓冲、95%
总仓位或强制调仓过程。标准 `set_holdings`、`liquidate` 和 LEAN 订单 API 均可用。

`af_rebalance_daily_weights(target_weights, tag)` 是可选 Daily 组合执行工具。
只有源码实际调用该 helper 时，Acceptance A2 才要求其 staged execution 完成；
普通 LEAN 订单路径不需要伪造 staged 事件。

## Worker 失败路径

Worker 失败时不会调用 Acceptance。Backend 收集：

- 完整 Worker 结果；
- 完整控制台日志；
- details 中的全部失败订单及对应 OrderEvents；
- 每个失败点之前最近的组合快照。

details 不可用时仍进入 Repair，并携带 details 错误及完整日志。运行失败和
Acceptance revise 共用最多三次源码修改，每次修改后重新运行 Worker。

## Provider 与格式稳定性

Provider 空响应或无效 JSON 最多重试一次，第二次关闭 thinking。调用 Trace 保存
全部原始响应和累计 token，不保存 API Key。JSON 解析与语义 schema 重试共享两次
模型调用总预算，避免嵌套成四次。

Backend 兼容顶层对象以及 `output`、`report`、`result` 外壳。Acceptance
API/格式重试不消耗源码 Repair 次数。

## A1–A5

- A1：成交数量、非零持仓快照和最大总敞口；Backend 硬事实守卫。
- A2：数据、特征/信号、模型/预测、决策、订单、成交的真实因果链；Agent 判断。
- A3：Traditional、ML、Hybrid 声明与实际决策路径一致；Agent 判断。
- A4：输入、标签、训练截止和交易时刻无前视；Agent 判断。
- A5：共享设置与成交股票白名单；Agent 判断，Backend 对成交集合做硬守卫。

收益、Sharpe、CAGR、回撤和是否战胜基线不属于资格验收；它们用于 Results、PK 和
Robustness Lab。

## 验证

```powershell
$env:PYTHONPATH='.;backend'
.\.venv\Scripts\python.exe -m pytest backend/tests -q

$env:PYTHONPATH='lean_worker'
.\.venv\Scripts\python.exe -m pytest lean_worker/tests -q
```
