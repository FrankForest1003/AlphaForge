# AlphaForge 项目使用与进度对齐指南

> 更新时间：2026-07-22
> 适用对象：AlphaForge 全体组员、后续接入项目的开发者
> 当前阶段：ExperimentContract、四基线后端批处理和真实 Baseline Classroom 已打通；AI Agent Runtime 等待成员 D 接入

## 1. 先看结论

目前已经可以通过 Streamlit 前端创建统一实验合同，并由 FastAPI 后端把四个公共基线依次提交给本地 QuantConnect LEAN Worker。四个策略使用同一组日期、股票、资金、费用、滑点、风险限制、数据版本和随机种子，结果会被标准化后显示在 Baseline Classroom。

当前可真实运行的主链路是：

```text
Streamlit 前端
  → 创建并冻结 ExperimentContract
  → FastAPI 创建 Battle 和四基线 Batch
  → 本地 LEAN Worker 串行执行四个策略
  → 解析并标准化指标、净值曲线和回撤曲线
  → Baseline Classroom 展示与重试
```

当前尚未接通的是 AI Forge / Multi-Agent 优化链路。后端会明确返回 `501 agent_runtime_not_configured`，这是为成员 D 预留的接口边界，不是当前部署故障。

## 2. 项目模块和责任边界

| 目录 | 当前用途 | 注意事项 |
|---|---|---|
| `frontend/` | Streamlit 页面、实验配置、基线状态和结果展示 | 不直接执行 LEAN，不自行计算最终指标 |
| `backend/` | FastAPI、ExperimentContract、Battle/Batch 编排、SQLite 持久化 | 只编排任务，不包含策略公式 |
| `lean_worker/` | 隔离的本地 LEAN Runtime、策略注册、数据、任务和结果解析 | 真实数据、任务和结果目录不会提交到 Git |
| `shared/contracts/` | 跨模块 JSON Schema | 已实现 ExperimentContract；其余合同应评审后再冻结 |
| `qc_strategies/` | 团队维护的策略来源和成员贡献 | 长期应作为策略 source of truth |
| `lean_worker/strategies/approved/` | 实际部署到 Worker 的已批准策略 | 目前仍需人工保持与 `qc_strategies/` 同步 |
| `agent/` | 成员 D 的 Multi-Agent Runtime 预留目录 | 不应绕过 ExperimentContract、信息边界和 Validator |
| `docs/research/` | 论文和研究材料 | 已放入 9 篇论文及索引说明 |

运行端口：

| 服务 | 地址 |
|---|---|
| Streamlit 前端 | <http://127.0.0.1:8501> |
| FastAPI 后端及文档 | <http://127.0.0.1:8000/docs> |
| LEAN Worker API | <http://127.0.0.1:18081/docs> |

服务之间通过 Docker 内部网络通信。外部端口变化不会改变后端访问 Worker 的内部地址 `http://lean-worker:8081`。

## 3. 第一次使用

### 3.1 环境要求

- Windows 10/11 或可运行 Docker Desktop 的环境；
- Docker Desktop 已启动；
- 建议至少预留 8 GB 内存和足够的磁盘空间；
- 如果本机没有行情数据，需要自己的 Tiingo API Token；
- 仓库路径中可以包含中文，但执行命令时应先进入仓库根目录。

### 3.2 创建本地环境文件

在项目根目录执行：

```powershell
Copy-Item .env.example .env
```

然后编辑根目录 `.env`：

```dotenv
ALPHAFORGE_API_TOKEN=请换成本机随机字符串
TIINGO_API_TOKEN=
TIINGO_START_DATE=2014-01-01
ALPHAFORGE_AUTO_GENERATE_SAMPLE_DATA=false
ALPHAFORGE_FRONTEND_PORT=8501
ALPHAFORGE_BACKEND_PORT=8000
ALPHAFORGE_WORKER_PORT=18081
```

不要把 `.env`、Tiingo Token 或真实行情数据提交到 Git。

### 3.3 新机器准备真实行情数据

当前开发机器已经有完整 30 股票以及 SPY、QQQ 数据。新机器克隆仓库后不会自动获得这些数据，因为市场数据受许可约束并且被 Git 忽略。

在新机器上可以使用 Worker 自带脚本：

```powershell
Set-Location lean_worker
powershell.exe -ExecutionPolicy Bypass -File .\scripts\configure.ps1
powershell.exe -ExecutionPolicy Bypass -File .\scripts\data-sync.ps1 -Full
Set-Location ..
```

脚本会要求输入自己的 Tiingo Token。详细说明见 `lean_worker/docs/FULL_USER_GUIDE_zh.md` 和 `lean_worker/docs/DATA_SOURCE_AND_LICENSE_zh.md`。

## 4. 启动、检查和停止项目

### 4.1 启动全部服务

在仓库根目录执行：

```powershell
docker compose up -d --build
```

首次构建 LEAN 镜像可能需要较长时间。后续没有 Dockerfile 或依赖变更时，可直接执行：

```powershell
docker compose up -d
```

### 4.2 检查服务状态

```powershell
docker compose ps
```

正常情况下，以下三个容器都应显示 `healthy`：

- `alphaforge-lean-worker-1`
- `alphaforge-backend-1`
- `alphaforge-frontend-1`

也可以检查后端聚合健康状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/health | ConvertTo-Json -Depth 10
```

关键字段应为：

```text
status = ok
backend = healthy
lean_worker.status = ok
lean_worker.real_data_ready = true
agent_runtime = not_configured
```

其中 `agent_runtime = not_configured` 是当前预期状态。

### 4.3 查看日志

```powershell
docker compose logs --tail 100 backend
docker compose logs --tail 100 frontend
docker compose logs --tail 100 lean-worker
```

持续跟踪某个服务时可添加 `-f`，按 `Ctrl+C` 只会退出日志查看，不会停止容器。

### 4.4 停止服务

```powershell
docker compose stop
```

停止并移除容器但保留数据卷：

```powershell
docker compose down
```

不要随意添加 `-v`，因为它会删除后端 SQLite 数据卷。LEAN 的行情和结果位于宿主机 `lean_worker/workspace/`，也不要手工清理，除非确认不再需要审计记录。

## 5. 前端标准操作流程

启动成功后打开 <http://127.0.0.1:8501>。

### Step 1：Rules & Strategy

1. 选择开始和结束日期；
2. 选择股票池，允许从 30 股票白名单中选择 5–30 只；
3. 正式标准实验应使用完整 30 只股票；
4. 设置初始资金、交易费、滑点和最大回撤门槛；
5. 当前建议优先使用 `Guided Mode`；
6. 点击 `Lock contract and continue`。

合同冻结后，Human、四基线和后续 AI 候选必须使用相同实验条件。后端会计算合同 SHA-256，避免某个策略暗中改变日期、费用或股票池。

当前 Live 模式下的自由 `LEAN Code` admission endpoint 尚未实现，因此该入口会被禁用；这不影响四公共基线运行。

### Step 2：Admission Check

在 Guided Mode 下点击 `Run admission checks`，确认股票白名单、仓位限制和不可变合同检查通过，然后点击 `Run four public baselines`。

当前 Guided Human 策略主要用于锁定产品流程，还没有作为第五条真实 LEAN 策略进入最终比较。不要在汇报中把它描述成“已完成 Human 全量回测”。

### Step 3：Baseline Comparison

LEAN Worker 一次只运行一个任务，四策略会串行执行。页面会显示：

- 每个策略的任务状态和 Worker Run ID；
- Sharpe、CAGR、MDD、Turnover、Fees；
- 是否满足比较资格；
- 净值曲线、回撤曲线和课堂解释。

运行期间点击 `Refresh baseline jobs` 获取最新状态。不要因为一个任务仍在运行就重启 Docker。

若某个任务失败或结果不完整，点击：

```text
Retry incomplete baseline batch
```

失败批次会被保留为审计历史，新重试会创建新的 Batch，不会覆盖旧记录。

### Step 4 以后

AI Candidates、最终比较和 Learning Review 页面目前属于预留/原型阶段。真实 Live 流程会停在 `AI Forge awaiting member-D Agent Runtime`，需要成员 D 接入后才能解锁真实候选生成。

## 6. 当前四个公共基线

所有基线统一使用：Daily 数据、Monthly 调仓、Long-only、无杠杆、允许现金、SPY Benchmark、QQQ 风险过滤、固定费用/滑点、固定随机种子，以及相同 ExperimentContract。

| 基线 | 类型 | 核心逻辑 | Worker Strategy ID |
|---|---|---|---|
| Momentum Rank | Traditional | 横截面动量排序，持有正动量 Top 3 | `classic_30_stock_top3_momentum_v1` |
| Mean Reversion | Traditional | 对短期弱势股票进行横截面均值回归排序 | `classic_30_stock_mean_reversion_v1` |
| Gradient Boosting | Machine Learning | Walk-forward GradientBoostingRegressor 预测未来 21 日相对 SPY Alpha | `ml_30_stock_gradient_boosting_v1` |
| Hybrid ML + Minimum Variance | Hybrid | 传统动量、Gradient Boosting 和 Ledoit-Wolf 最小方差分配 | `hybrid_30_stock_ml_momentum_min_variance_v1` |

策略执行文件位于：

```text
lean_worker/strategies/approved/
```

策略注册信息位于：

```text
lean_worker/strategies/registry/
```

新增或修改策略时，两者必须保持一致，并更新相关测试和 Worker 包校验和。

## 7. 结果和数据保存在哪里

### 7.1 LEAN Worker 宿主机目录

```text
lean_worker/workspace/data/       行情数据和数据质量清单
lean_worker/workspace/jobs/       每次任务的策略副本与实际 LEAN 配置
lean_worker/workspace/results/    标准化结果、原始 LEAN 输出和日志
lean_worker/workspace/models/     ML 模型产物
lean_worker/workspace/service/    Worker 任务索引
lean_worker/workspace/locks/      LEAN 单进程锁
```

单次运行的关键文件：

```text
results/<run_id>/manifest.json             数据、策略、参数和版本审计信息
results/<run_id>/console.log               LEAN 完整控制台日志
results/<run_id>/result.json                标准化结果
results/<run_id>/alphaforge_details.json    曲线、持仓、订单、信号和 ML 证据
```

### 7.2 后端状态

Battle、ExperimentContract、Batch 和四条 Run 记录保存在 Docker 命名卷 `alphaforge_backend-data` 中的 SQLite 数据库。旧失败任务不会因为新重试而消失。

## 8. 常用 API

| 方法 | 地址 | 用途 |
|---|---|---|
| GET | `/v1/health` | 后端、Worker、数据和 Agent Runtime 状态 |
| GET | `/v1/catalog/universe` | 30 股票白名单和最少选择数 |
| GET | `/v1/catalog/baselines` | 四基线注册信息 |
| POST | `/v1/battles` | 创建并冻结 ExperimentContract |
| GET | `/v1/battles/{battle_id}` | 查询 Battle |
| POST | `/v1/battles/{battle_id}/baselines/run` | 创建新的四基线 Batch |
| GET | `/v1/battles/{battle_id}/baselines` | 查询并刷新最新 Batch |
| GET | `/v1/baseline-batches/{batch_id}` | 按 Batch ID 查询 |
| POST | `/v1/battles/{battle_id}/rounds/{round_id}/ai-forge` | 成员 D 待实现；当前返回 501 |

可在 <http://127.0.0.1:8000/docs> 直接查看和试用接口。

## 9. 开发和测试

在仓库根目录运行全套现有测试：

```powershell
$env:PYTHONPATH = "backend;lean_worker;frontend"
.\.venv\Scripts\python.exe -m pytest `
    backend\tests `
    lean_worker\tests `
    frontend\tests `
    -q
```

截至 2026-07-22，结果为：

```text
23 passed
```

修改 Worker 或策略后至少需要：

1. 运行测试；
2. 重建 Worker：`docker compose up -d --build --force-recreate lean-worker`；
3. 使用最少 5 股票做短区间真实 LEAN 冒烟回测；
4. 确认 `status=completed` 且 `eligible_for_comparison=true`；
5. 再运行完整 30 股票正式实验。

短区间冒烟回测只验证执行正确性，不能用来宣称策略有投资表现优势。

## 10. 常见问题

### 10.1 `Bind for 127.0.0.1:18081 failed: port is already allocated`

先检查旧容器：

```powershell
docker ps --format "table {{.Names}}\t{{.Ports}}"
```

如果是旧 AlphaForge Worker，可以先停止旧容器。也可以在根目录 `.env` 中修改：

```dotenv
ALPHAFORGE_WORKER_PORT=18082
```

然后重新执行 `docker compose up -d`。根项目后端仍通过 Docker 内部端口访问 Worker，不需要改后端代码。

### 10.2 页面一直显示 running

- 点击 `Refresh baseline jobs`；
- 使用 `docker compose ps` 确认 Worker 健康；
- 使用 `docker compose logs --tail 100 lean-worker` 查看日志；
- 四任务串行属于正常设计，完整 30 股票实验会明显慢于短冒烟测试。

### 10.3 页面显示 failed 和 None 指标

先查看对应 Run ID：

```text
lean_worker/workspace/results/<run_id>/console.log
lean_worker/workspace/results/<run_id>/result.json
```

修复后点击 `Retry incomplete baseline batch`。旧失败 Batch 不会自动变成成功。

### 10.4 `real_data_ready=false`

说明本机没有完整行情数据或质量检查未通过。重新执行 `lean_worker/scripts/data-sync.ps1 -Full`，不要启用伪造数据代替正式实验。

### 10.5 AI Forge 返回 501

这是当前预期行为。成员 D 接入 Agent Runtime 前，不要用 Mock 候选或静态页面数据冒充真实 Agent 结果。

## 11. 截至 2026-07-22 的项目进度

### 11.1 已完成并验证

- [x] 30 股票固定白名单，前端统一最低选择 5 只；
- [x] SPY、QQQ 作为分析依赖；
- [x] 不可变 ExperimentContract 和 SHA-256；
- [x] FastAPI Battle、Batch、Run 编排及 SQLite 持久化；
- [x] 四基线统一参数批量提交；
- [x] 两个传统、一个纯 ML、一个 Hybrid 基线；
- [x] 本地真实 LEAN Worker 和 Tiingo 数据；
- [x] 费用、滑点、无杠杆和先卖后买调仓；
- [x] 标准化指标、净值、回撤、订单和 ML 证据；
- [x] Streamlit Live Baseline Classroom；
- [x] 失败批次审计保留和前端重试；
- [x] 9 篇论文归档及研究索引；
- [x] 四策略真实短回测均已达到 `completed + eligible`；
- [x] 当前自动化测试 23 项全部通过；
- [x] frontend、backend、lean-worker 三容器健康运行。

最近修复的关键问题：

1. 当前 LEAN Python 环境未导出 `SlippageModel` 导致四策略共同初始化失败；
2. LEAN 原始 `config.json` 的多行 JSONC `parameters` 没有被正确替换，导致合同参数只写入审计清单但未真正进入引擎；
3. Hybrid 在现金缓冲下需要显式完成减仓后再提交买单，否则可能出现购买力拒单。

### 11.2 当前未完成或仅为原型

- [ ] Guided Human 策略的真实全量 LEAN 回测；
- [ ] 自由 LEAN Code 的隔离 Admission、静态检查和 Smoke Endpoint；
- [ ] 成员 D 的 Baseline Analyst、Traditional/ML/Hybrid Designer、Risk Reviewer、Validator、Code Generation 和 Repair Runtime；
- [ ] 三个 AI Candidate 的真实 Spec → Code → LEAN 闭环；
- [ ] AI 信息边界的自动化泄漏测试；
- [ ] 候选稳健性实验、样本外评估和消融实验；
- [ ] Human、四基线、三候选和 Benchmark 的最终统一 Judge；
- [ ] 正式完整 30 股票结果冻结和展示用图表导出；
- [ ] `qc_strategies/` 到 Worker approved 策略的自动部署流程；
- [ ] 除 ExperimentContract 外其他共享 Schema 的团队评审和冻结；
- [ ] Proposal、Poster、Demo Video、Showcase 页面和用户测试材料。

### 11.3 不要误报的内容

- 当前已经验证的是四基线真实执行链路，不代表策略已经取得优秀或稳健收益；
- 短区间 Smoke 结果不能用作论文或展示中的正式性能结论；
- AI Candidate 页面中的现有静态内容不是成员 D Runtime 的真实输出；
- `agent_runtime=not_configured` 不影响基线，但说明端到端 AI 优化项目尚未完成；
- 正式研究结论必须来自完整 30 股票、统一合同和冻结数据版本的可复现实验。

## 12. 下一阶段建议和交接

### 成员 C 当前建议任务

1. 使用修复后的系统重新运行完整 30 股票四基线；
2. 冻结正式 ExperimentContract、数据版本和 Run IDs；
3. 检查四策略指标、订单、费用、曲线和比较资格；
4. 完善 Baseline Classroom 的解释文本、错误展开和结果导出；
5. 为成员 D 准备只包含“合同 + 四基线公共证据”的输入 Bundle；
6. 与团队确认 Human 初始策略由哪个 Guided 模板真实执行。

### 成员 D 接入要求

成员 D 应接入后端预留的 AI Forge 边界，而不是让前端直接调用 LLM。至少需要定义：

```text
输入：ExperimentContract + 四公共基线标准化证据
禁止输入：Human 策略代码、Human 参数、Human 回测结果和 Human 分析
输出：Traditional、ML、Hybrid 三条结构化 Candidate Spec
后续：Validator → QC Python → LEAN Smoke → Repair → Full Backtest
```

Agent 输出不得自报收益指标；所有最终指标只能来自 LEAN。Risk Reviewer 和确定性 Validator 必须能拒绝候选，Repair 只能修实现错误，不能暗中改变策略语义。

### 团队合并前检查

- 是否修改了冻结合同或白名单；
- 是否改变了数据日期、成本、滑点或随机种子；
- 是否补充了测试；
- 是否做过真实 LEAN Smoke；
- 是否保留 Run ID 和 manifest；
- 是否把密钥、行情 ZIP、SQLite 或大型结果误加入 Git；
- 是否清楚标注 Mock、Prototype 和 Real Evidence。

## 13. 相关文档

- 仓库结构：`README_REPOSITORY_LAYOUT.md`
- 后端说明：`backend/README.md`
- 前端说明：`frontend/README.md`
- ExperimentContract：`shared/contracts/README.md`
- LEAN 完整使用指南：`lean_worker/docs/FULL_USER_GUIDE_zh.md`
- LEAN API：`lean_worker/docs/API_GUIDE_zh.md`
- LEAN 故障排查：`lean_worker/docs/TROUBLESHOOTING_zh.md`
- 结果结构：`lean_worker/docs/RESULT_SCHEMA.md`
- 研究论文索引：`docs/research/README.md`

如果本文件与代码实际行为不一致，应以真实接口、测试和 LEAN 运行证据为准，并在同一次合并中更新本文件。
