# AlphaForge API 指南

Base URL：

```text
http://127.0.0.1:18081
```

除 `/health` 外，请求头必须包含：

```http
X-Worker-Token: <ALPHAFORGE_API_TOKEN>
```

## 接口

```text
GET  /health
GET  /v1/data/status
GET  /v1/universes/default
GET  /v1/strategies
GET  /v1/jobs?limit=50
POST /v1/jobs
GET  /v1/jobs/{run_id}
GET  /v1/jobs/{run_id}/result
GET  /v1/jobs/{run_id}/artifacts
GET  /v1/jobs/{run_id}/artifacts/{name}
```

## 提交任务

```json
{
  "strategy_id": "classic_30_stock_top3_momentum_v1",
  "parameters": {
    "start_date": "2015-01-02",
    "end_date": "latest",
    "symbols": "MSFT,AAPL,NVDA,GOOGL,AMZN,META,AVGO,ASML,AMD,ORCL,JPM,BRK.B,V,LLY,JNJ,ABBV,TMO,WMT,COST,PG,KO,MCD,CAT,HON,UNP,ETN,XOM,LIN,NEE,PLD",
    "top_k": "3"
  },
  "timeout_seconds": 3600
}
```

`latest` 在入队前解析为数据 Catalog 的 `common_end_date`，实际解析结果会保存在 job record 和 result manifest。

## 状态

```text
queued
running
completed
failed
timeout
completed_with_data_gaps
```

只有 `completed` 且 `evaluation.eligible_for_comparison=true` 的结果可以进入 Agent 排名。

## 并发

当前采用 FIFO 单执行器和 LEAN Launcher 文件锁。多个请求可以排队，但同一时间只执行一个回测，以避免共享 Launcher config 和计算资源竞争。
