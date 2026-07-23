# AlphaForge Backend

FastAPI Backend 校验七项 RunSettings，并编排四个公共基线、一个 Human 策略、三个 Designer 候选、Repair 和 Acceptance Agent 闭环。Agent 的 DeepSeek 客户端、提示词和角色实现位于仓库根目录 `agent/`。

运行状态保存在内存中，同一时间只编排一个 Forge Run。三个 Designer 的首次 DeepSeek 请求并行执行；策略任务由 Worker 串行执行。

Human 策略支持两种输入。`code` 模式提交完整 `UserStrategy` Python 源码；`guided` 模式提交信号、回看期、调仓频率和持仓数，Backend 生成完整源码。Human 由 Worker 直接回测并返回指标、行为事实和源码，不进入 Repair 或 Acceptance。

DeepSeek 使用环境变量 `API_KEY`、`BASE_URL`、`MODEL` 和 `THINKING_ENABLED`。官方 QuantConnect 文档在启动时只用于资源健康检查；Designer 和 Repair 使用紧凑能力契约、轨道配方和已验证模板，避免把约 22 万 token 的完整文档重复注入每次请求。

Designer 返回结构化 `design` 和完整源码。源码先通过确定性 AST/契约预检，预检通过后才提交 Worker；预检会检查 schedule 重载、AlphaForge 证据字典签名、明显不可达信号分支和未来标签处理。静态失败、运行失败和验收否决都会携带稳定分类进入 Repair。Repair 输出首个中断阶段、实际修改过的完整源码和 1–3 条修改摘要，修复后必须重新预检、回测和验收。三类失败共享最多三次源码修改。

Worker Attempt 持久化完整 LEAN 日志；传给 Acceptance 和 Repair 的 Agent 上下文分别限制为 12,000 和 20,000 字符的关键摘录，保留错误、源码行号、统计信息及日志首尾。

模型只遗漏外层 JSON closure 时，客户端会恢复已完整返回的结构化设计和源码，并记录恢复解析模式。每轮 Acceptance 同时保存 AST 语义变化、结果变化、行为变化和已解决检查；Evidence-only 修订与真正改变交易行为的修订分开标记。

最近五次完成的 Forge Run 另存于 `backend/workspace/run_history/`，用于 Best-of-Five PK Arena。Human 历史不会进入 Agent Trace 或任何模型上下文。

Acceptance Agent 不接收 LEAN 文档、QC 模板或基线结果。候选只有在实际投资行为、数据到订单因果链、轨道完整性、时间完整性和共享设置全部通过后才进入 `accepted`。API 返回最后验收报告和完整验收历史；累计 token 包含 Designer、Repair 和 Acceptance 调用。

`AlphaForgeBaseAlgorithm` 为所有策略设置固定 2% 购买力缓冲。Designer 模板使用内部 95%最大总仓位，但不设置统一单标的仓位上限，并给出单标的和多标的 History DataFrame 范式；日线 long-only 组合通过 `af_rebalance_to_weights` 等待减仓成交后再提交买单。这些不是 RunSettings 字段。

接口：

- `GET /v1/health`
- `GET /v1/catalog/universe`
- `GET /v1/catalog/baselines`
- `POST /v1/forge-runs`，请求体包含 `settings` 和 `human_strategy`
- `GET /v1/forge-runs/{run_id}`
- `GET /v1/forge-history`
- `GET /v1/forge-history/{run_id}`

RunSettings 的股票池必须为完整 30 股票目录中的 5–30 只。

本地测试：

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```
