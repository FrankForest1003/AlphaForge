# AlphaForge LEAN Worker

Worker 在 Docker 中运行真实 QuantConnect LEAN Python 回测。它提供四个公共基线任务和任意 Python 源码任务，所有任务串行执行。

## 接口

- `GET /health`
- `GET /v1/data/status`
- `POST /v1/jobs`：提交四个注册基线之一
- `POST /v1/custom-jobs`：提交 Designer 生成的完整 Python 源码
- `GET /v1/jobs/{run_id}`
- `GET /v1/jobs/{run_id}/result`
- `GET /v1/jobs/{run_id}/log`：读取完整 LEAN 控制台日志
- `GET /v1/jobs/{run_id}/details`：读取订单、持仓、敞口和调仓原始明细

自定义源码不经过包黑名单、AST 规则或关键词过滤。LEAN 负责加载、编译和执行；错误进入结果的 `errors`。

策略使用标准 QuantConnect 生命周期。`AlphaForgeBaseAlgorithm` 提供通用设置和记录辅助，不设置现金缓冲、总仓位上限或默认下单过程。Worker 在任务副本中增加运行观测包装，因此策略自己的 `on_data`、`on_order_event` 和结束回调不会遮蔽明细记录。

## 四个公共基线

- Momentum Rank
- Mean Reversion
- Gradient Boosting
- Hybrid ML + Minimum Variance

它们读取相同的候选池、日期、初始资金、benchmark、交易费和滑点。策略内部的信号、调仓、持仓数量和风险规则是各基线自身实现。

四个公共基线显式使用可选的分阶段 long-only 调仓工具。Designer 和 Repair 上下文通过 `self.af_rebalance_daily_weights` 提供同一执行能力，供 Daily 组合轮换需要等待卖出资金时选择。该 helper 处理移除、减仓成交、完整 Daily bar 后的买入计算、限价重定价和终态订单，并按调用方传入的目标权重执行。调用策略采用足以完成多 Daily bar 执行周期的目标更新频率。生成策略仍自行决定仓位和现金预留。LEAN 的订单错误会被严格解析为失败，不会因为已经生成收益指标而被忽略。

## 数据与结果

行情位于 `workspace/data/`。数据同步使用：

```bash
./scripts/data-sync.sh
```

任务和结果位于 `workspace/jobs/` 与 `workspace/results/`。对外结果只有：

- `run_id`
- `status`
- `summary.cagr`
- `summary.sharpe_ratio`
- `summary.maximum_drawdown`
- `summary.end_equity`
- `errors`

每个任务目录同时保留 `console.log` 和 `alphaforge_details.json`。Backend 通过日志接口取得完整控制台日志；失败时通过 details 构造 Repair 使用的失败订单事实，成功时构造 Acceptance Agent 使用的精确行为事实。
