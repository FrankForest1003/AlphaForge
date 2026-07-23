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

所有继承 `AlphaForgeBaseAlgorithm` 的策略自动使用固定 2%购买力缓冲。该默认位于共享基类，不需要每个基线或 Designer 重复设置。

## 四个公共基线

- Momentum Rank
- Mean Reversion
- Gradient Boosting
- Hybrid ML + Minimum Variance

它们读取相同的候选池、日期、初始资金、benchmark、交易费和滑点。策略内部的信号、调仓、持仓数量和风险规则是各基线自身实现。

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

每个任务目录同时保留 `console.log` 和 `alphaforge_details.json`。Backend 通过日志接口取得完整控制台日志，通过 details 接口构造 Acceptance Agent 使用的精确行为事实。
