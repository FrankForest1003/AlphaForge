# 故障排查

## 端口被占用

修改 `.env`：

```dotenv
ALPHAFORGE_PORT=18082
```

然后：

```powershell
.\scripts\shutdown.ps1
.\scripts\start.ps1
```

## 401 Invalid worker token

调用方 Token 与 `.env` 中 `ALPHAFORGE_API_TOKEN` 不一致。不要使用 Tiingo Token 调 Worker API。

## 409 dataset is not ready

运行：

```powershell
.\scripts\data-sync.ps1 -Full
.\scripts\data-status.ps1
```

## Tiingo 401/403

- Token 错误；
- Token 前后有空格；
- 账户权限或许可不适用；
- 重新运行 configure。

## Tiingo 429

达到小时或日请求上限。同步器会自动退避；不要连续重复启动全量同步。稍后重新执行增量同步即可继续覆盖更新。

## 某个 ticker 返回空数据

查看：

```text
workspace/data/lean/alphaforge-catalog/quality_report.json
```

确认 `provider_errors`。重点检查 `BRK.B` 的 Tiingo 映射是否仍是 `BRK-B`；如供应商调整代码，在 `config/universe_whitelist_v1.0.json` 修改 `tiingo_ticker` 后重新同步。

## Mac Apple Silicon 运行较慢

v1.1.3 固定 `linux/amd64`，目的是与 Windows 保持同一二进制环境。不要自行改成 arm64 后继续声称结果完全可比，除非重新完成跨架构 reference tests。

## Docker build 失败

```bash
docker compose --env-file .env build --progress=plain backtest-runtime
```

检查网络、磁盘、Docker 内存以及 GitHub、Microsoft、Anaconda/conda-forge 可访问性。

## LEAN failed_requests > 0

- 检查 `quality_report.json`；
- 检查每个 ZIP 是否存在；
- 确认策略只访问白名单、SPY、QQQ；
- 运行全量 data sync；
- 查看对应 `console.log`。

## 服务关闭后数据是否还在

`stop`、`shutdown` 和默认 `uninstall` 都不会删除 `workspace/data`。只有带 `RemoveData/--remove-data` 和强制确认的卸载命令会删除数据。
