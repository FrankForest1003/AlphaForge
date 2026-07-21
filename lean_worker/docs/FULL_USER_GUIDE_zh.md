# AlphaForge Local LEAN Runtime v1.1.3 全套使用说明

本文覆盖：部署、配置、真实数据下载、数据更新、启动、API 调用、结果查看、关闭、备份、迁移、恢复和卸载。

---

## 一、部署前准备

### 1. 支持平台

- Windows 11 + Docker Desktop；
- macOS Intel + Docker Desktop；
- macOS Apple Silicon + Docker Desktop。

Compose 固定使用：

```yaml
platform: linux/amd64
```

Apple Silicon 会通过 Docker Desktop 的 amd64 兼容层运行，以优先保证与 Windows 使用相同 LEAN、Python.NET 和 ML 二进制环境。

### 2. 本机要求

- Docker Desktop 已安装并启动；
- Docker 使用 Linux containers；
- Git 为可选；
- 首次镜像构建和行情下载需要可访问互联网；
- 建议为 Docker 分配足够内存和磁盘空间；
- 默认端口 `18081` 未被占用。

验证 Docker：

```powershell
# Windows
docker version
docker compose version
docker info
```

```bash
# macOS
docker version
docker compose version
docker info
```

### 3. Tiingo Token

1. 注册自己的 Tiingo 账户；
2. 在 Tiingo API 页面获得 Token；
3. 不要把 Token 提交到 Git；
4. 不要把 `.env` 发给别人；
5. 不要把下载后的真实行情放入公开仓库或压缩包。

本项目需要 32 个代码：30 股票 + SPY + QQQ。首次全量同步对每个代码发起一次 EOD 请求。

---

## 二、解压与目录选择

### Windows

建议：

```text
D:\Code\alphaforge-local-lean-runtime-v1.1.3
```

不要放在：

- OneDrive 正在实时同步的目录；
- 包含特殊权限限制的系统目录；
- 网络映射盘。

### macOS

建议：

```text
~/Code/alphaforge-local-lean-runtime-v1.1.3
```

进入目录：

```bash
cd ~/Code/alphaforge-local-lean-runtime-v1.1.3
chmod +x scripts/*.sh
```

---

## 三、首次配置

### Windows

```powershell
Set-Location D:\Code\alphaforge-local-lean-runtime-v1.1.3

powershell.exe `
  -ExecutionPolicy Bypass `
  -File .\scripts\configure.ps1
```

脚本会隐藏输入 Tiingo Token，并生成：

```text
.env
```

还会生成一个 64 字符随机本地 API Token。

指定端口：

```powershell
powershell.exe `
  -ExecutionPolicy Bypass `
  -File .\scripts\configure.ps1 `
  -Port 18082
```

### macOS

```bash
./scripts/configure.sh
```

指定端口：

```bash
./scripts/configure.sh 18082
```

### `.env` 关键字段

```dotenv
ALPHAFORGE_PORT=18081
ALPHAFORGE_API_TOKEN=<随机本地 Token>
RUNTIME_VERSION=1.1.3
LEAN_REF=0269115d3cfbf691c7a0b7cfcc9ed412cafb91f6
TIINGO_API_TOKEN=<你自己的 Token>
TIINGO_START_DATE=2014-01-01
ALPHAFORGE_AUTO_GENERATE_SAMPLE_DATA=false
```

---

## 四、首次构建和启动

### Windows

```powershell
powershell.exe `
  -ExecutionPolicy Bypass `
  -File .\scripts\start.ps1
```

### macOS

```bash
./scripts/start.sh
```

首次执行会：

1. 下载 .NET SDK/runtime 基础镜像；
2. clone 固定 commit 的 LEAN；
3. 应用 Python.NET one-shot shutdown 补丁；
4. 构建 LEAN Launcher；
5. 创建 Python 3.11 Conda 环境；
6. 安装 ML 依赖；
7. 启动 FastAPI；
8. 绑定到 `127.0.0.1:18081`。

成功标志：

```text
ALPHAFORGE_LOCAL_RUNTIME_STARTED
```

打开：

```text
http://127.0.0.1:18081/docs
```

此时服务已启动，但真实数据尚未下载，`real_data_ready` 会是 `false`。

---

## 五、首次下载 2014 至最近完整交易日的数据

### Windows

```powershell
powershell.exe `
  -ExecutionPolicy Bypass `
  -File .\scripts\data-sync.ps1 `
  -Full
```

### macOS

```bash
./scripts/data-sync.sh --full
```

同步器会：

1. 暂停 API 容器，避免边下载边回测；
2. 按白名单读取 30 股票 + SPY + QQQ；
3. 从 Tiingo 下载 adjusted EOD OHLCV；
4. 从 2014-01-01 开始；
5. 请求到当前日期，但实际写入供应商已经发布的最近完整交易日；
6. 转换为 LEAN daily ZIP；
7. 写 neutral map/factor compatibility files；
8. 校验日期、OHLC、Volume、重复行和相对 SPY 缺失；
9. 生成 Catalog 和 Checksums；
10. 数据成功后重新启动 API。

成功标志：

```text
ALPHAFORGE_REAL_DATA_READY
```

### 数据位置

```text
workspace/data/lean/
├── equity/usa/daily/
├── equity/usa/factor_files/
├── equity/usa/map_files/
├── market-hours/
├── symbol-properties/
├── alternative/interest-rate/
└── alphaforge-catalog/
```

### Catalog

```text
workspace/data/lean/alphaforge-catalog/
├── symbols.csv
├── availability.csv
├── quality_report.json
├── dataset_manifest.json
├── corporate_actions.json
└── checksums.json
```

---

## 六、检查数据是否完整

### Windows

```powershell
.\scripts\data-status.ps1
```

### macOS

```bash
./scripts/data-status.sh
```

必须看到：

```json
{
  "ready": true,
  "required_symbol_count": 32,
  "available_symbol_count": 32,
  "missing_symbols": [],
  "failed_quality_symbols": []
}
```

`common_end_date` 是所有 32 个代码共同可用的最新日期。提交任务时，`end_date=latest` 会自动解析成这个日期。

---

## 七、完整验收

### Windows

```powershell
powershell.exe `
  -ExecutionPolicy Bypass `
  -File .\scripts\test.ps1
```

### macOS

```bash
./scripts/test.sh
```

默认依次运行：

```text
classic_30_stock_top3_momentum_v1
ml_30_stock_gradient_boosting_v1
```

验收检查：

- `status=completed`；
- `clean_shutdown=true`；
- `failed_requests=0`；
- `error_lines=[]`；
- 数据 manifest `ready=true`；
- Equity、Benchmark、Position snapshots 非空；
- ML 训练和预测非空。

最终成功标志：

```text
ALPHAFORGE_LOCAL_RUNTIME_PASS
```

只测试 Classic：

```powershell
.\scripts\test.ps1 `
  -Strategies "classic_30_stock_top3_momentum_v1"
```

```bash
./scripts/test.sh classic_30_stock_top3_momentum_v1
```

---

## 八、通过 API 使用

### 1. 读取 Token

Windows：

```powershell
$Lines = Get-Content .env
$Port = (($Lines | Where-Object { $_ -match '^ALPHAFORGE_PORT=' } | Select-Object -Last 1).Split('=',2)[1]).Trim()
$Token = (($Lines | Where-Object { $_ -match '^ALPHAFORGE_API_TOKEN=' } | Select-Object -Last 1).Split('=',2)[1]).Trim()
$BaseUrl = "http://127.0.0.1:$Port"
$Headers = @{"X-Worker-Token"=$Token}
```

macOS：

```bash
PORT="$(grep '^ALPHAFORGE_PORT=' .env | cut -d= -f2-)"
TOKEN="$(grep '^ALPHAFORGE_API_TOKEN=' .env | cut -d= -f2-)"
BASE_URL="http://127.0.0.1:${PORT}"
```

### 2. 数据状态

```powershell
Invoke-RestMethod "$BaseUrl/v1/data/status" -Headers $Headers
```

```bash
curl -H "X-Worker-Token: ${TOKEN}" "${BASE_URL}/v1/data/status"
```

### 3. 策略列表

```powershell
Invoke-RestMethod "$BaseUrl/v1/strategies" -Headers $Headers
```

### 4. 提交 Classic 30 股票任务

```powershell
$Body = @{
  strategy_id = "classic_30_stock_top3_momentum_v1"
  timeout_seconds = 3600
  parameters = @{
    start_date = "2015-01-02"
    end_date = "latest"
    lookback = "126"
    top_k = "3"
    target_gross = "0.95"
    max_position_weight = "0.35"
    risk_filter_enabled = "true"
    risk_sma_period = "200"
  }
} | ConvertTo-Json -Depth 10

$Job = Invoke-RestMethod `
  -Method Post `
  -Uri "$BaseUrl/v1/jobs" `
  -Headers $Headers `
  -ContentType "application/json" `
  -Body $Body

$RunId = $Job.run_id
```

### 5. 自定义 10–30 股票子池

```powershell
$Body = @{
  strategy_id = "classic_30_stock_top3_momentum_v1"
  timeout_seconds = 3600
  parameters = @{
    symbols = "MSFT,AAPL,NVDA,GOOGL,AMZN,META,AVGO,AMD,ORCL,JPM"
  }
} | ConvertTo-Json -Depth 10
```

规则：

- 只能使用冻结白名单内的股票；
- 至少 10 只；
- 最多 30 只；
- `SPY` 和 `QQQ` 由策略自动加入，不写入 `symbols`。

### 6. 提交 ML 任务

```powershell
$Body = @{
  strategy_id = "ml_30_stock_gradient_boosting_v1"
  timeout_seconds = 7200
  parameters = @{
    start_date = "2016-01-04"
    end_date = "latest"
    training_bars = "420"
    forecast_horizon = "21"
    top_k = "3"
    random_seed = "42"
  }
} | ConvertTo-Json -Depth 10
```

### 7. 轮询状态

```powershell
while ($true) {
  $Status = Invoke-RestMethod "$BaseUrl/v1/jobs/$RunId" -Headers $Headers
  Write-Host "state=$($Status.state)"
  if ($Status.state -eq "completed") { break }
  if ($Status.state -in @("failed","timeout","completed_with_data_gaps")) {
    $Status | ConvertTo-Json -Depth 20
    throw "Backtest failed"
  }
  Start-Sleep -Seconds 3
}
```

### 8. 读取结果

```powershell
$Result = Invoke-RestMethod "$BaseUrl/v1/jobs/$RunId/result" -Headers $Headers
$Result.summary
$Result.portfolio.final_positions
$Result.execution.closed_trades
$Result.ml.training_runs
```

结果文件同时保存在：

```text
workspace/results/<run_id>/result.json
```

---

## 九、数据更新

Tiingo EOD 通常在交易日结束后发布并可能继续修正。更新脚本请求到当前日期，但只会写入供应商实际返回的完整日线。

由于本项目使用 dividend/split adjusted OHLCV，新的公司行为可能使更早的 adjusted 历史值发生重述。因此脚本默认执行全历史刷新，以保持整段 2014 至今序列内部一致。

### Windows：默认完整刷新

```powershell
.\scripts\data-sync.ps1
```

### macOS：默认完整刷新

```bash
./scripts/data-sync.sh
```

以下写法含义相同：

```powershell
.\scripts\data-sync.ps1 -Full
```

```bash
./scripts/data-sync.sh --full
```

### 可选增量模式

```powershell
.\scripts\data-sync.ps1 -Incremental
```

```bash
./scripts/data-sync.sh --incremental
```

增量模式只往前重取 14 天并按日期合并，适合临时检查最近行情；正式报告、跨平台复现和最终策略比较前必须再次执行完整刷新。

### 指定日期

```powershell
.\scripts\data-sync.ps1 `
  -StartDate "2014-01-01" `
  -EndDate "2026-07-20" `
  -Full
```

### API 限流

出现 HTTP 429 时，同步器会读取 `Retry-After` 或执行指数退避。首次同步不要重复快速执行多次。同步失败时 API 容器会保持停止状态，避免使用部分更新；修复 Token、网络或限流问题后重新运行同步命令。

---

## 十、查看运行状态和日志

### Windows

```powershell
.\scripts\status.ps1
.\scripts\logs.ps1
```

### macOS

```bash
./scripts/status.sh
./scripts/logs.sh
```

退出实时日志：

```text
Ctrl+C
```

不会停止容器。

---

## 十一、停止、关闭和重新启动

### 暂停服务，保留容器

Windows：

```powershell
.\scripts\stop.ps1
```

macOS：

```bash
./scripts/stop.sh
```

恢复：

```powershell
.\scripts\start.ps1
```

```bash
./scripts/start.sh
```

### 重启容器

```powershell
.\scripts\restart.ps1
```

```bash
./scripts/restart.sh
```

### 完整关闭 Compose

删除容器和 Compose 网络，但保留镜像、数据、结果和 `.env`：

```powershell
.\scripts\shutdown.ps1
```

```bash
./scripts/shutdown.sh
```

---

## 十二、备份

备份包括：

- LEAN 数据；
- 回测结果；
- ML 模型；
- API 任务索引。

不包括 `.env` 和 Token。

### Windows

```powershell
.\scripts\backup.ps1
```

### macOS

```bash
./scripts/backup.sh
```

默认输出：

```text
workspace/backups/alphaforge-backup-YYYYMMDD-HHMMSS.tar.gz
```

---

## 十三、迁移到另一台 Windows 或 Mac

1. 在原电脑运行 backup；
2. 复制本 v1.1.3 项目包；
3. 复制 backup archive；
4. 新电脑安装 Docker Desktop；
5. 解压项目；
6. 在新电脑运行 configure，使用新电脑自己的 Tiingo Token；
7. 运行 start，构建镜像；
8. 运行 restore；
9. 运行 data-status；
10. 运行 test。

### Windows 恢复

```powershell
.\scripts\restore.ps1 `
  -Archive ".\workspace\backups\alphaforge-backup-xxxx.tar.gz" `
  -Force
```

### macOS 恢复

```bash
./scripts/restore.sh workspace/backups/alphaforge-backup-xxxx.tar.gz --force
```

备份中的行情仍受原数据供应商许可约束，只能在许可范围内迁移和内部使用。

---

## 十四、卸载

### 1. 只删除容器和网络，保留镜像与数据

```powershell
.\scripts\uninstall.ps1
```

```bash
./scripts/uninstall.sh
```

### 2. 同时删除 Docker 镜像，保留数据

```powershell
.\scripts\uninstall.ps1 -RemoveImage
```

```bash
./scripts/uninstall.sh --remove-image
```

### 3. 删除镜像、真实行情、结果、模型和任务记录

先备份，再执行：

```powershell
.\scripts\uninstall.ps1 `
  -RemoveImage `
  -RemoveData `
  -Force
```

```bash
./scripts/uninstall.sh --remove-image --remove-data --force
```

最后手动删除项目文件夹，才能完成源代码层面的彻底删除。

注意：卸载脚本不会替你删除 `.env`。删除项目文件夹前确认不再需要其中的 Token。

---

## 十五、服务边界

当前版本是课程项目级本地回测后端：

- 日频 US Equity；
- 固定白名单；
- 串行单任务执行；
- 本地 `127.0.0.1`；
- 回测，不是实盘交易；
- 不提供分钟级行情；
- 不提供官方 QuantConnect Security Master；
- 不允许通过 API 上传任意 Python 执行；
- 只运行注册策略。

这套边界可以保证 AlphaForge 的可复现性、安全性和展示稳定性。
