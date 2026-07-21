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
