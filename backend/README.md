# AlphaForge Backend

FastAPI Backend 负责校验统一 RunSettings，并编排四个公共基线、一个 Human
策略，以及 Traditional、ML、Hybrid 三条 AI 候选链。Agent 实现在仓库根目录
`agent/`。

## 候选执行链

1. Designer 根据四个公共基线和共享设置返回结构化设计与完整源码。
2. 窄预检只检查 Python 语法，以及明确的文件、进程、网络和动态执行能力。
3. LEAN Worker 运行采用标准 `initialize`、`on_data`、`on_order_event` 和
   `on_end_of_algorithm` 的策略。
4. Worker 失败时，Backend 收集完整结果、完整日志、全部失败订单、
   OrderEvents 和失败前持仓快照，直接交给 Repair；即使 details 不可用也会修复。
5. Worker 成功时，独立 Acceptance Agent 审核 A1–A5 并决定
   `accept/revise`。Backend 只检查 JSON/决策一致性，并用运行事实约束 A1、
   用成交白名单约束 A5，不替代 A2–A4 的语义判断。
6. 每次源码修改都必须重新运行 Worker。运行失败与 Acceptance revise 共用最多
   三次源码修改预算；Acceptance API/格式重试不消耗该预算。

Worker 失败不会调用 Acceptance。Worker Attempt Trace 保留每次完整源码、
参数、Worker 结果和控制台日志。DeepSeek 空响应或无效 JSON 最多重试一次，
第二次关闭 thinking；Designer、Repair、Acceptance 的 JSON/语义重试共享同一
两次模型调用上限。

## 策略运行约定

`AlphaForgeBaseAlgorithm` 是轻量辅助层：费用/滑点、benchmark、History
拆分、结构化信号/ML/订单证据，以及可选
`af_rebalance_daily_weights(target_weights, tag)`。它不设置固定现金缓冲、
95% 总仓位或强制下单流程。生成策略可以使用标准 `set_holdings`、`liquidate`
和 LEAN 订单 API；只有 Daily 组合轮换需要等待减仓资金时才选择分阶段 helper。

Worker 只在任务副本中注入运行观察包装，因此不会修改保存的候选源码。四个公共
基线均使用标准生命周期。

## Human、历史与教育层

Human 支持 `code` 和 `guided` 两种输入，直接由 Worker 回测，不进入 Designer、
Repair 或 Acceptance 上下文。最近五次 Forge Run 保存到
`backend/workspace/run_history/`，用于 Best-of-Five PK、结果对比、教学建议和
鲁棒性实验。Human 信息不会写入 Agent 上下文或 Agent Trace。

## 主要接口

- `GET /v1/health`
- `GET /v1/catalog/universe`
- `GET /v1/catalog/baselines`
- `POST /v1/forge-runs`
- `GET /v1/forge-runs/{run_id}`
- `GET /v1/forge-history`
- `GET /v1/forge-history/{run_id}`
- `POST /v1/forge-runs/{run_id}/robustness`

RunSettings 使用完整 30 股票目录中的 5–30 只股票。

## 本地测试

Windows PowerShell：

```powershell
$env:PYTHONPATH='.;backend'
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```
