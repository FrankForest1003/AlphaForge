# AlphaForge 当前实现交接快照

> 更新时间：2026-07-22
> 用途：供组员和后续 AI 快速恢复项目上下文。完整说明见根目录 `TEAM_PROJECT_GUIDE_zh.md`。

## 当前可用链路

```text
Streamlit 锁定 ExperimentContract 与 Human 策略
  → Guided：受控模板直接准入
  → LEAN Code：冻结源码 SHA-256 → AST 受限检查 → 隔离 LEAN Smoke
  → FastAPI 创建 Human + 四公共基线 Batch
  → LEAN Worker FIFO 执行五条真实任务
  → Baseline Classroom 展示指标、曲线、Run ID、资格和结果哈希
```

默认使用完整 30 股票白名单，允许选择 5–30 只。Human 和四基线必须共享日期、股票池、资金、费用、滑点、风险限制、数据版本、随机种子和 ExperimentContract 哈希。

## Human 策略入口

Guided 新建 Battle 只暴露以下三个模板，Worker ID 均不与公共基线重复：

| 模板 | Worker strategy ID |
|---|---|
| Multi-Horizon Momentum | `guided_30_stock_multi_horizon_momentum_v1` |
| Risk-Adjusted Momentum | `guided_30_stock_risk_adjusted_momentum_v1` |
| Low Volatility | `guided_30_stock_low_volatility_v1` |

旧 `momentum_rank`、`mean_reversion` 映射只用于读取历史 Battle，不再提供给新用户。

LEAN Code 的可运行 starter 位于 `frontend/mock_data.py`。用户代码必须定义：

```text
class UserStrategy(AlphaForgeBaseAlgorithm)
initialize_strategy(self)
on_alpha_data(self, data)
on_alpha_end(self) → ALPHAFORGE_USER_STRATEGY_COMPLETED
```

必须读取合同参数并使用 `af_configure_security`、`af_use_security_benchmark`。禁止网络、子进程、任意文件访问、动态执行和危险反射。后端 AST 检查是准入层，Worker 还有第二层 envelope 检查；通过静态检查后仍必须完成真实隔离 Smoke。准入代表可执行，不代表盈利。

## 四个公共基线

```text
classic_30_stock_top3_momentum_v1
classic_30_stock_mean_reversion_v1
ml_30_stock_gradient_boosting_v1
hybrid_30_stock_ml_momentum_min_variance_v1
```

Baseline Comparison 中 Human 使用 `role=human`，公共策略使用 `role=baseline`。成员 D 的 AI evidence bundle 必须只读取四条 `role=baseline`，不得包含 Human 源码、参数、结果或页面分析。

## 关键代码位置

- `backend/app/schemas/experiment.py`：ExperimentContract、Battle 和 CodeValidation 合同；
- `backend/app/services/code_validation.py`：自定义代码 AST 准入；
- `backend/app/services/baseline_service.py`：Battle、Smoke、Human + 四基线编排；
- `lean_worker/app/service.py`：注册策略和不可变 custom source 任务；
- `lean_worker/strategies/approved/`：实际执行策略；
- `frontend/app.py`：用户工作流和 Baseline Classroom；
- `frontend/mock_data.py`：可运行 LEAN Code starter；
- `backend/app/main.py`：FastAPI 路由；
- `agent/`：成员 D 尚未实现的 Agent Runtime 边界。

## 关键 API

```text
POST /v1/battles
GET  /v1/catalog/guided-strategies
POST /v1/strategies/code/validate
GET  /v1/strategies/code/validate/{battle_id}
POST /v1/battles/{battle_id}/baselines/run
GET  /v1/battles/{battle_id}/baselines
POST /v1/battles/{battle_id}/rounds/{round_id}/ai-forge  # 当前预期 501
```

## 最近验证证据

- 自动化测试：`32 passed`；
- Code Battle：`btl-730ca5f0006b`；
- Code Smoke：`20260722-080721-1048ad3f`，`completed`；
- 五策略 Batch：`base-958138878df9`，Human + 四基线全部 `completed + eligible`；
- Multi-Horizon：`20260722-080849-99ff5007`，`completed + eligible`；
- Risk-Adjusted：`20260722-080932-75a2c8e2`，`completed + eligible`；
- Low Volatility：`20260722-080932-40bbb4b7`，`completed + eligible`；
- frontend、backend、lean-worker 健康端点均返回 200。

这些是短区间工程验证，不得当作正式投资业绩。正式报告必须重新运行完整 30 股票、冻结合同和数据版本，并记录最终 Run ID。

## 运行与验证

```powershell
docker compose up -d
$env:PYTHONPATH='backend;lean_worker'
.\.venv\Scripts\python.exe -m pytest backend/tests frontend/tests lean_worker/tests -q
```

页面：<http://127.0.0.1:8501>
API 文档：<http://127.0.0.1:8000/docs>

## 尚未完成

- 成员 D 的 Baseline Analyst、Traditional/ML/Hybrid Designer、Risk Reviewer、Validator、Code Generation 与 Repair Runtime；
- 三个 AI Candidate 的真实 Spec → Code → LEAN 闭环；
- 自动化 AI 信息泄漏测试；
- Final Comparison、Learning Review、跨轮导出和恢复的真实后端闭环。

当前 `501 agent_runtime_not_configured` 是预期行为。接入 Agent 时不要让前端直接调用 LLM，也不要给 Agent Human 侧信息。
