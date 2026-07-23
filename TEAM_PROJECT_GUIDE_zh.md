# AlphaForge 当前项目指南

AlphaForge 是一个本地演示系统：四个公共策略先在相同设置下完成真实 LEAN 回测。Human 策略和 Traditional、ML、Hybrid 三个 DeepSeek Designer 共享相同的运行设置；三个 Designer 的首次 API 请求并行发出，Human 与三个生成候选再由同一个 LEAN Worker 串行回测。运行失败由 Repair Agent 修复；运行成功的 Designer 候选由 Acceptance Agent 按 A1–A5 验收。验收否决同样进入 Repair、重新回测和重新验收。每个 Designer 候选最多修改源码三次。

## 服务

- `frontend/`：Vite + React 单页应用，包含创建运行、实时进度、结果比较和策略源码视图。
- `agent/`：DeepSeek 客户端、固定提示词、Designer、Repair 和 Acceptance Agent。
- `backend/`：运行设置、八个策略与 Agent 闭环的编排和状态查询。
- `lean_worker/`：真实 QuantConnect LEAN 执行环境。

启动：

```bash
cp .env.example .env
docker compose up --build
```

浏览器打开 `http://127.0.0.1:8501`。

## 一次 Forge Run

1. 用户在前端 checkbox 中选择股票候选池，并设置日期、初始资金、benchmark、交易费和滑点。
2. 用户用完整 Python 源码提供 Human 策略，或选择信号、回看期、调仓频率和持仓数，由 Backend 生成完整 Human 源码。
3. Worker 依次运行 Momentum、Mean Reversion、Gradient Boosting、Hybrid 四个公共基线。
4. Backend 把四个基线的四项摘要指标同时交给三个 Designer，并在等待响应期间提交 Human 策略。
5. 三个 Designer 各自返回一个 `source_code`；Worker 继续串行运行三个候选策略。
6. Designer 候选运行失败时，Backend 读取完整控制台日志和 Worker details，从失败订单、订单事件和最近组合快照构造运行失败事实，再以受上下文预算约束的精确证据视图调用 Repair Agent。
7. Designer 候选运行成功时，Backend 从 Worker 明细构造订单、持仓、敞口、信号、模型训练和预测事实，并由 Acceptance Agent 检查 A1 实际投资行为、A2 数据到订单因果链、A3 轨道完整性、A4 时间完整性和 A5 共享设置。
8. 验收否决时，完整验收报告进入 Repair；修复后的完整源码重新回测并重新验收。运行错误修复与验收否决修复共享最多三次修改。
9. Human 结果忠实展示 Worker 状态、指标、行为事实和完整源码，不调用 Designer、Repair 或 Acceptance Agent。
10. 前端自动轮询运行状态，通过 URL 中的 `run_id` 打开运行，并在策略工作区展示和下载 Human 与三个 Designer 的完整源码。

Backend 的普通运行状态保存在进程内存中。每次 Designer、Repair 和 Acceptance 调用另有独立的持久化 Agent Trace，保存在 `backend/workspace/forge_traces/`；Backend 重启后仍可通过 Trace 接口读取。Worker 的日志和结果文件保存在 `lean_worker/workspace/`。

## 当前进度（2026-07-23）

- React 前端、FastAPI Backend、真实本地 LEAN Worker 和四个公共基线已经接通。
- DeepSeek Designer、Repair、Acceptance 闭环已经接通；API Key 只通过根目录 `.env` 注入。
- Backend 按轮次持久化 DeepSeek 请求中的动态上下文、SDK 原始响应、原始响应文本、解析结果、token usage、错误和耗时，并把每版候选源码与对应 Worker 结果、完整日志、运行失败事实、行为事实及验收报告关联起来。
- 所有策略使用标准 QuantConnect `initialize`、`on_data`、`on_order_event` 和 `on_end_of_algorithm` 生命周期。Worker 在任务副本中增加只读观测包装，策略重载标准回调不会中断订单、持仓和结果记录。
- `AlphaForgeBaseAlgorithm` 只提供手续费、滑点、benchmark、History DataFrame 和行为记录辅助。组合规模、现金预留和订单执行由策略自己决定。
- 四个公共基线显式使用可选的分阶段 long-only 调仓工具；Designer 和 Repair 模板提供 `self.af_rebalance_daily_weights`，用于 Daily 组合轮换中等待移除和减仓成交后再建立目标仓位。策略保持对目标权重、总敞口和现金预留的完整控制。
- Designer 和 Repair 模板使用 Daily 股票数据边界，展示 `af_split_history_frames` 按大写 ticker 字符串取值，并使用结构化信号、训练和预测事件记录实际执行路径。使用分阶段 helper 时，信号或预测期限、目标更新频率和多 Daily bar 执行周期保持一致。
- Agent 请求使用有明确上限的动态日志证据视图；Worker Attempt Trace 继续保存完整 `result.json` 和完整控制台日志。DeepSeek 空内容或非法 JSON 会在关闭 Thinking 后重试一次。

当前运行验证：

| 策略 | Worker Run | 区间 | 状态 | 订单 | 持仓快照 |
|---|---|---|---|---:|---:|
| META 跳空回归 | `20260723-102822-79e4255d` | 2024-01-29 至 2024-02-09 | completed | 9 | 17 |
| Guided Human | `20260723-103411-3610719b` | 2024-01-02 至 2024-06-28 | completed | 22 | 147 |
| Momentum Rank | `20260723-102918-bede0576` | 2024-01-02 至 2024-06-28 | completed | 27 | 151 |
| Mean Reversion | `20260723-102918-05df0bbe` | 2024-01-02 至 2024-06-28 | completed | 17 | 139 |
| Gradient Boosting | `20260723-102918-cb9f47c9` | 2024-01-02 至 2024-06-28 | completed | 42 | 157 |
| Hybrid | `20260723-102918-88d93f45` | 2024-01-02 至 2024-06-28 | completed | 27 | 147 |

这些运行使用 5 股票池、初始资金 100,000 美元、10 bps 交易费和 5 bps 滑点，用于确认标准生命周期、观测包装和可选 Baseline 执行对象均能在真实 LEAN 中完成。

完整 Forge Run `forge-f6290fbc9330` 使用 2020-01-02 至 2024-12-31 的相同 5 股票设置完成。Traditional、ML 和 Hybrid 分别在 1、3、1 次 Repair 后通过真实 Worker 回测与 A1–A5 Acceptance；最终成交数分别为 103、153、162，模型轨道分别记录 60 次训练/412 次预测和 60 次训练/300 次预测。

## RunSettings

所有八个策略共享以下设置：

| 字段 | 含义 |
|---|---|
| `symbols` | 用户勾选的股票候选池，至少一只 |
| `start_date` | 回测开始日期 |
| `end_date` | 回测结束日期 |
| `initial_cash` | 初始资金 |
| `benchmark` | 比较基准，当前数据目录提供 SPY |
| `transaction_cost_bps` | 交易费用，单位为基点 |
| `slippage_bps` | 滑点，单位为基点 |

调仓频率、持仓数量、仓位、模型、风险信号和随机种子属于策略实现，由每个基线或 Designer 自己决定。

RunSettings 不包含现金缓冲、总仓位或单标的仓位字段。Designer 自己实现组合规模、现金预留和下单过程；Repair 可以根据实际订单错误降低总仓位、增加现金、重新计算数量或改变下单顺序。

## DeepSeek 上下文

Backend 使用 `.env` 中的 `API_KEY`、`BASE_URL`、`MODEL` 和 `THINKING_ENABLED`，通过 OpenAI Python SDK 调用兼容的 DeepSeek Chat Completions API。

每次 Designer 请求按以下顺序组织：

1. system prompt；
2. 可运行的 `UserStrategy` QuantConnect Python 模板；
3. `docs/lean/text/alphaforge-python-v1/writing-algorithms-python.txt` 的完整纯文本内容；
4. Designer 类型、RunSettings、四个公共基线结果；
5. 输出要求：一个 JSON 对象，其中只有完整的 `source_code`。

三个首次设计请求互相独立并同时发出。候选回测失败时，Repair 请求仍按模板、完整原文文档、动态修复请求的顺序组织；动态部分包含完整候选源码、Worker 结果证据视图、LEAN 控制台日志证据视图和结构化运行失败事实。常规大小的动态证据保持原样；超过上下文预算时保留错误邻域、开头、结尾、原始长度和明确省略标记。运行失败事实逐项关联失败订单、订单事件、失败前最近组合快照和对应日志原文。发送内容不包含 API Key、本地路径、Git 信息、源码哈希或 Worker 实现。

Acceptance Agent 只在 Worker 返回 `completed` 后调用。它不接收 LEAN 文档、QC 模板或基线结果；上下文由固定 A1–A5 规则、轨道要求、RunSettings、完整候选源码、Worker 结果证据视图、控制台日志证据视图、精确行为事实和验收轮次组成。行为事实包含订单与持仓统计、分阶段调仓开始/完成/替换和取消订单计数，以及结构化信号、模型训练和最近预测事件。A1 要求至少一笔成交、至少一个非零持仓快照和正的最大总敞口。使用 `self.af_rebalance_daily_weights` 的策略还必须在 A2 中证明至少一轮分阶段调仓完成。A1–A5 全部通过才接受候选，收益和风险指标不属于验收条件。

每个 Forge Run 的 Agent Trace 独立于普通运行响应。Trace 保存模型、thinking、token 上限等 API 参数和每轮发生变化的上下文，并保存 API 返回的完整 SDK 响应结构、原始 `content` 与解析后的 JSON。system prompt、LEAN 文档、QC 模板、固定验收规则和固定输出说明仍会正常发送给 Agent，但不在每次 Trace 中重复保存。Trace 不保存或返回 `API_KEY`。它还逐轮保存送入 Worker 的完整源码、运行参数、Worker Run ID、`result.json` 内容、完整控制台日志、行为事实、验收报告和该轮结果。Worker 原始 details 继续只保存在 Worker 结果目录，不在 Trace 中复制第二份。

Designer 模板使用标准 QuantConnect 生命周期，并给出两种 History DataFrame 范式：单标的使用普通 `history(TradeBar, ...)`，多标的使用 `af_split_history_frames(history(...))`，返回字典通过 `symbol.value.upper()` 对应的大写 ticker 键取值。当前本地股票数据为 Daily。策略自行选择 `set_holdings`、订单 API、现金预留和调仓顺序；当组合轮换中的买入依赖待完成卖单释放的资金时，可以把完整 long-only 目标权重映射交给 `self.af_rebalance_daily_weights`。该 helper 分阶段完成移除、减仓和买入，并按调用方权重执行。策略通过 `af_record_signal`、`af_record_ml_training` 和 `af_record_ml_prediction` 留下实际执行事实。

## API

Backend：

- `GET /v1/health`
- `GET /v1/catalog/universe`
- `GET /v1/catalog/baselines`
- `POST /v1/forge-runs`，请求体包含 `settings` 和 `human_strategy`
- `GET /v1/forge-runs/{run_id}`
- `GET /v1/forge-runs/{run_id}/trace`，返回可跨 Backend 重启读取的完整 Agent 复盘记录

Worker：

- `GET /health`
- `GET /v1/data/status`
- `POST /v1/jobs`
- `POST /v1/custom-jobs`
- `GET /v1/jobs/{run_id}`
- `GET /v1/jobs/{run_id}/result`
- `GET /v1/jobs/{run_id}/log`
- `GET /v1/jobs/{run_id}/details`

## Worker 执行边界

Worker 是本机可信执行服务。自定义源码进入 Worker 后经过：

1. 可选的本地 API token 校验；
2. 行情数据就绪检查；
3. 写入本次任务的 Python 文件，并在任务副本中增加运行观测包装；
4. 交给真实 LEAN Python 引擎加载和执行；
5. 从 LEAN 控制台提取运行状态和四项摘要指标，并保留完整日志；订单、持仓、敞口和调仓明细通过只读 details 接口供 Backend 构造运行失败事实或验收事实。

Worker 不做 Python 包黑名单、AST 准入、源码关键词过滤或 import 过滤。NumPy、pandas、scikit-learn、SciPy、XGBoost 和 LightGBM 可以被策略直接导入。Python 或 LEAN 错误会作为该候选的真实失败结果返回。

Worker `result.json` 只包含 `run_id`、`status`、四项 `summary` 和 `errors`。完整控制台日志保存在对应结果目录。

## 测试

```bash
PYTHONPATH=.:backend .venv/bin/python -m pytest backend/tests -q
cd frontend && npm test
cd lean_worker && PYTHONPATH=. ../.venv/bin/python -m pytest tests -q
```

机器学习和深度学习相关的本地实验环境使用 conda `ml_env`；金融学相关实验使用 `fin_env`。Docker 中的 LEAN Worker 使用自身固定的 Python 环境。
