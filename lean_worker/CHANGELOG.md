# Changelog

## 1.1.3 - 2026-07-20

- Fixed ML 30-stock history extraction when a frozen current ticker has no rows in an early backtest window.
- Replaced LEAN PandasMapper mapped-key `.loc`/`.xs` lookups with integer-position grouping over symbols actually present in the History MultiIndex.
- Missing-history stocks such as LIN before 2018 are now recorded in `skipped_symbols` and do not terminate monthly walk-forward training.
- Added regression tests for absent symbols and LEAN-like Symbol objects in History DataFrames.
- No Tiingo data re-download is required.

## 1.1.3 - 2026-07-20

- Fixed SPY benchmark creation so Daily-only datasets no longer request `equity/usa/hour/spy.zip`.
- Added staged sell/reduce-before-buy portfolio rebalancing for Daily data to prevent transient buying-power failures.
- Added a 2% free-portfolio buffer and disabled the minimum-order-margin filter for reference Top-3 strategies.
- Classic 30-stock momentum now ranks all currently ready securities instead of blocking until every current ticker has full history.
- ML 30-stock strategy now skips symbols with insufficient history and records the eligible/skipped universe in JSON diagnostics.
- Updated runtime version to 1.1.3.

## 1.1.1-hotfix

- Fix Classic and ML 30-stock strategies using an invalid three-argument batch `set_holdings` overload.
- Batch portfolio targets now call `set_holdings(targets, True)`, which is supported by LEAN Python.
- No data re-download is required.

## 1.1.1

- 从 2 股票部署验证包升级为可长期使用的本地 30 股票 LEAN 回测后端。
- 加入冻结的 AlphaForge 30 股票白名单，以及 SPY Benchmark、QQQ 风险过滤依赖。
- 新增 Tiingo EOD 真实行情同步器，支持 2014-01-01 至最近完整交易日的全量下载和增量更新。
- 使用 Tiingo adjusted OHLCV + LEAN `DataNormalizationMode.RAW`，避免重复复权。
- 新增 `dataset_manifest.json`、`quality_report.json`、`availability.csv`、`checksums.json` 和公司行为记录。
- 新增 `/v1/data/status`、`/v1/universes/default`、`/v1/jobs`。
- `end_date=latest` 自动解析为 32 个代码共同可用的最近日期。
- 新增 `classic_30_stock_top3_momentum_v1`。
- 新增 `ml_30_stock_gradient_boosting_v1`。
- 结果 JSON 新增 dataset manifest、Benchmark、Cash 和 Exposure 曲线。
- 新增配置、数据同步、状态、备份、恢复、停止、关闭和卸载脚本。
- 新增完整中文部署与生命周期手册。
- 真实行情不包含在 ZIP 中；每位用户必须使用自己的 Tiingo Token，并遵守内部使用许可。

## 1.0.1

- 修复详细结果记录器对 LEAN Python `datetime.datetime` 使用 .NET `ToString()` 导致的运行时异常。
- 时间序列化现在优先使用 Python `isoformat()`，并继续兼容 Python.NET 暴露的 .NET `DateTime`。
- 新增 Python datetime、date 与 .NET-like 对象的回归测试。

## 1.0.0

- 首个本地 Docker、Windows/macOS 可迁移版本。
