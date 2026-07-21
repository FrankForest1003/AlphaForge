# HTTP API

Base path 为 `/v1`，媒体类型为 `application/json`。HTTP 层为异步作业边界；当前仓库实现领域闭环和 Provider 端口。

## POST /v1/optimisations

提交 `OptimizationRequest`，其中包含父 `StrategySpec`、五个标准化证据结果和确定性选择约束。

- 必须提供 `Idempotency-Key`。
- 成功返回 `202 Accepted`、`optimization_id`、`queued` 和状态 URL。
- Test 证据、Schema 错误或策略规则错误返回 `422`。
- 相同幂等键对应不同请求体返回 `409`。

## GET /v1/optimisations/{optimization_id}

处理中返回作业状态；完成后返回 `OptimizationResult`。

```text
queued
→ summarizing_evidence
→ designing
→ validating_spec
→ compiling_strategy
→ validating_code
→ reviewing_code_risk
→ smoke_testing
→ backtesting
→ post_backtest_analysis
→ selecting
→ completed | failed
```

## POST /v1/backtests

提交 `BacktestSubmission`，返回 `202 Accepted` 和 `run_id`。请求使用代码产物 ID，不传开发机绝对路径。

## GET /v1/backtests/{run_id}

处理中返回状态；完成后返回标准化 `BacktestResult`。

## Local LEAN Worker API

平台通过 `backend.app.services.LeanWorkerClient` 访问仅监听 localhost 的 Worker。除健康检查外，请求使用独立的 `X-Worker-Token`。

```text
GET  /health
GET  /v1/data/status
POST /v1/strategies/generated
POST /v1/jobs
GET  /v1/jobs/{run_id}
GET  /v1/jobs/{run_id}/result
GET  /v1/jobs/{run_id}/artifacts
```

生成策略部署必须携带完整源码、算法类名、完成标志、源码 SHA-256、Spec SHA-256、默认参数和必需 Symbol。Worker 再次执行 AST 与运行时合同检查，并使用原子替换写入被 Git 忽略的运行目录。只有 `completed` 且 `evaluation.eligible_for_comparison=true` 的结果会被归一化为可选候选。

## 错误格式

```json
{
  "error": {
    "code": "TEST_EVIDENCE_FORBIDDEN",
    "message": "Held-out test evidence cannot be used during optimisation.",
    "request_id": "req_01J...",
    "details": [
      {
        "path": "/evidence/4/dataset_split",
        "reason": "must not be test"
      }
    ]
  }
}
```

错误响应不得包含提示词、密钥、Provider 原始响应或本地路径。
