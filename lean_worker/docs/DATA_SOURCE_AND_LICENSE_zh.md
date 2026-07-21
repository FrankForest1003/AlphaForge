# 数据来源、复权和许可说明

## 数据源

AlphaForge v1.1.3 使用用户自行配置的 Tiingo End-of-Day Prices API。

同步范围：

- 30 只冻结白名单股票；
- SPY；
- QQQ；
- 2014-01-01 至供应商最近完整交易日；
- Daily OHLCV。

## 复权政策

同步器优先使用：

```text
adjOpen
adjHigh
adjLow
adjClose
adjVolume
```

写入 LEAN 后，策略使用：

```python
DataNormalizationMode.RAW
```

避免重复复权。

同步器同时记录 Tiingo 返回的 `divCash` 与 `splitFactor` 到：

```text
alphaforge-catalog/corporate_actions.json
```

但 LEAN 使用的是 neutral compatibility factor/map files，不会再次应用这些公司行为。

## Security Master 限制

- 当前股票池按今天冻结的 ticker 回溯；
- META 等历史 ticker 变化由数据供应商历史序列承接，但 LEAN map file 不模拟官方 ticker-change Security Master；
- 当前股票池存在 survivorship selection；
- 不适合声称是无偏全市场历史 Universe；
- 适合固定资产池、相同数据条件下的策略对比。

## 许可

- ZIP 不包含真实市场数据；
- 每位用户使用自己的 Tiingo Token；
- `.env` 不提交 Git；
- `workspace/data` 不提交 Git；
- 内部研究用途不等于可公开再分发；
- 将数据提供给第三方、嵌入公开软件或托管给没有独立 Tiingo 账户的用户，可能需要 redistribution license；
- 展示许可范围内的数据或结果时，应按 Tiingo 要求保留 `Data sourced by Tiingo` attribution；
- 使用前由使用者自行确认账户类型和许可范围。

## 数据质量门槛

`quality_report.json` 的 `ready` 只有在以下条件满足时为 true：

- 32 个代码全部存在；
- 每个代码至少 1000 行；
- OHLCV 静态检查通过；
- 相对 SPY 日历缺失比例不超过 2%；
- 本次同步没有供应商请求错误。

回测结果进入 Agent 比较还要求：

```text
status=completed
failed_requests=0
error_lines=[]
clean_shutdown=true
```
