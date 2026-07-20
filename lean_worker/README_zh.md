# AlphaForge Local LEAN Runtime v1.1.3

一个可在 **Windows 11** 与 **macOS** 本地运行的 Docker 化 LEAN 回测服务，面向 AlphaForge 的固定 30 只美股股票池，支持传统策略、scikit-learn / XGBoost / LightGBM 类机器学习策略，并返回完整 JSON 结果。

> 真实市场数据不包含在本压缩包中。每位使用者必须使用自己的 Tiingo API Token 下载数据。数据只能按对应许可用于内部研究，不得随项目重新分发。

## 1. 本版本包含什么

- Docker Desktop 一键构建并运行 LEAN；
- Windows 与 macOS 共用 `linux/amd64` 容器环境；
- 固定 LEAN commit：`0269115d3cfbf691c7a0b7cfcc9ed412cafb91f6`；
- Python 3.11.11；
- NumPy、pandas、SciPy、scikit-learn、XGBoost、LightGBM、joblib；
- 30 只股票白名单；
- `SPY` Benchmark；
- `QQQ` 200 日均线风险过滤依赖；
- Tiingo EOD 真实行情完整下载与增量更新；
- 2014-01-01 至最近完整交易日的日线 OHLCV；
- 数据质量 Catalog 与 Checksums；
- Classic 30 股票 Top-3 Momentum 策略；
- ML 30 股票 Gradient Boosting 策略；
- FIFO 单任务 LEAN 执行队列；
- 完整 JSON：绩效、净值、回撤、Benchmark、现金、仓位、订单、成交、闭合交易、信号、ML 训练与预测；
- Windows/macOS 启动、测试、更新、备份、恢复、关闭和卸载脚本。

## 2. 股票池

### 30 只可交易股票

`MSFT, AAPL, NVDA, GOOGL, AMZN, META, AVGO, ASML, AMD, ORCL, JPM, BRK.B, V, LLY, JNJ, ABBV, TMO, WMT, COST, PG, KO, MCD, CAT, HON, UNP, ETN, XOM, LIN, NEE, PLD`

### 分析依赖

- `SPY`：Benchmark；
- `QQQ`：风险过滤。

Tiingo ticker 映射：`BRK.B → BRK-B`。LEAN 内部和网页展示仍使用 `BRK.B`。

## 3. 数据政策

本项目下载 Tiingo 的 adjusted OHLCV，并写成 LEAN Daily TradeBar ZIP。策略使用：

```python
DataNormalizationMode.RAW
```

这样可以避免二次复权。

生成的是 neutral compatibility map/factor files，适用于冻结的当前 ticker 股票池，但**不等同于 QuantConnect 官方 Security Master**。因此本项目适合课程研究、固定股票池策略比较和 Agent 优化，不应声称消除了 survivorship bias。

详细安装和使用流程见：

[docs/FULL_USER_GUIDE_zh.md](docs/FULL_USER_GUIDE_zh.md)

## 4. 最快部署流程

### Windows PowerShell

```powershell
Set-Location D:\Code\alphaforge-local-lean-runtime-v1.1.3

powershell.exe -ExecutionPolicy Bypass -File .\scripts\configure.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\data-sync.ps1 -Full
powershell.exe -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

### macOS Terminal

```bash
cd ~/Code/alphaforge-local-lean-runtime-v1.1.3
chmod +x scripts/*.sh

./scripts/configure.sh
./scripts/start.sh
./scripts/data-sync.sh --full
./scripts/test.sh
```

测试全部通过时输出：

```text
ALPHAFORGE_LOCAL_RUNTIME_PASS
```

## 5. 服务地址

```text
Swagger API:
http://127.0.0.1:18081/docs

Health:
http://127.0.0.1:18081/health
```

接口仅绑定 `127.0.0.1`，默认不会暴露到局域网或互联网。

## 6. 常用命令

### Windows

```powershell
# 状态
.\scripts\status.ps1

# 增量更新真实行情
.\scripts\data-sync.ps1

# 提交示例回测
.\scripts\submit-example.ps1

# 查看日志
.\scripts\logs.ps1

# 暂停容器
.\scripts\stop.ps1

# 恢复运行
.\scripts\start.ps1

# 删除容器和 Compose 网络，保留数据
.\scripts\shutdown.ps1
```

### macOS

```bash
./scripts/status.sh
./scripts/data-sync.sh
./scripts/submit-example.sh
./scripts/logs.sh
./scripts/stop.sh
./scripts/start.sh
./scripts/shutdown.sh
```

## 7. 目录

```text
workspace/
├── data/                 # LEAN 行情与数据 Catalog
├── results/<run_id>/     # result.json、console.log、manifest.json
├── jobs/<run_id>/        # 每次运行的策略副本和 config
├── models/<run_id>/      # ML 模型
├── service/              # API 任务索引
├── locks/                # LEAN/data update 文件锁
└── backups/              # 备份归档
```

## 8. 内置策略

### Classic

```text
classic_30_stock_top3_momentum_v1
```

- 月度调仓；
- 126 日动量；
- Top 3；
- Long-only；
- 总目标仓位 95%；
- 单股上限 35%；
- QQQ 200 日 SMA 风险过滤；
- 默认回测起点 2015-01-02；
- 默认终点自动解析为数据集共同最新日期。

### ML

```text
ml_30_stock_gradient_boosting_v1
```

- scikit-learn `GradientBoostingRegressor`；
- 月度 walk-forward 训练；
- 420 个交易日训练窗口；
- 21 个交易日预测目标；
- 30 股票横截面预测并选择 Top 3 正预测；
- 固定随机种子 42；
- 默认回测起点 2016-01-04，确保 2014 起的数据足够覆盖训练 warm-up；
- 输出每轮训练、特征重要性、全部股票预测和模型 SHA256。

## 9. 结果 JSON

```text
workspace/results/<run_id>/result.json
```

主要字段：

```text
run
strategy
environment
dataset
engine
summary
statistics
performance.equity_curve
performance.drawdown_curve
performance.benchmark_curve
performance.cash_curve
performance.exposure_curve
portfolio.position_snapshots
portfolio.final_positions
execution.orders
execution.order_events
execution.fills
execution.closed_trades
signals
ml.training_runs
ml.predictions
ml.model_artifacts
data_quality
evaluation
diagnostics
artifacts
```

## 10. 数据许可

Tiingo 的 API 数据默认用于内部使用。软件包采用“每个用户提供自己的 Token”的开发者模式，不携带、不公开、不重新分发真实行情。

完整说明见：

- `docs/FULL_USER_GUIDE_zh.md`
- `docs/DATA_SOURCE_AND_LICENSE_zh.md`
- `docs/API_GUIDE_zh.md`
- `docs/TROUBLESHOOTING_zh.md`
