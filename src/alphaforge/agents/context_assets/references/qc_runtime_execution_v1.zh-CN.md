# 本地 QC 运行时执行参考

来源：
- https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/warm-up-periods
- https://www.quantconnect.com/docs/v2/writing-algorithms/scheduled-events
- https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/position-sizing
获取日期：2026-07-20
适用 Profile：LEAN Python、日频美股、月度 long-only 调仓

## Warm-up

LEAN 在 Warm-up 期间重放历史数据，并且不允许在此期间交易。只要 `self.IsWarmingUp` 为 true，
每一条下单路径都必须直接返回。请求的 Warm-up 数量不能保证每个 Symbol 都具有同样数量的有效
观测值：低流动性、IPO 日期、缺失数据和市场交易时间都可能减少可用行数。代码在调仓时仍然必须
检查数据完整性。

```python
if self.IsWarmingUp:
    return
```

Warm-up 完成不能替代特征、标签或 estimator 的就绪检查。

## 月度 Schedule

向 `DateRules.MonthStart` 提供 Symbol 时，事件绑定到该 Symbol 当月第一个交易日，而不是日历月
第一天。`TimeRules.AfterMarketOpen(anchor, 30)` 把回调安排在该 Symbol 开盘 30 分钟后。

```python
self.Schedule.On(
    self.DateRules.MonthStart(anchor),
    self.TimeRules.AfterMarketOpen(anchor, 30),
    self.Rebalance,
)
```

Schedule 只能在 `Initialize` 中注册一次。即使如此，仍需要单独的同日保护，防止其他回调路径在同一天
再次调用调仓。

## 目标仓位

`SetHoldings(symbol, weight)` 根据目标组合权重计算订单数量并提交市价单。在增加新持仓前，可能需要
先减少现有仓位。对当前小型 long-only 组合，确定性骨架必须先清理未入选持仓，再应用受上限约束的
目标权重。

目标组合不变量为：

```text
selected_count <= top_k
每个目标权重 >= 0
每个目标权重 <= max_position_weight
目标权重总和 <= max_leverage
所有未入选但仍持有的 Symbol 都被清仓
```

如果分数构造失败或没有有效 Symbol，策略必须执行明确政策。AlphaForge v1 的安全政策是清理现有
持仓，而不是保留过期敞口。这一行为属于确定性骨架，不属于 Agent 生成区域。
