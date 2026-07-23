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
6. Designer 候选运行失败时，Backend 读取完整控制台日志并调用 Repair Agent。
7. Designer 候选运行成功时，Backend 从 Worker 明细构造订单、持仓、敞口和调仓事实，并由 Acceptance Agent 检查 A1 实际投资行为、A2 数据到订单因果链、A3 轨道完整性、A4 时间完整性和 A5 共享设置。
8. 验收否决时，完整验收报告进入 Repair；修复后的完整源码重新回测并重新验收。运行错误修复与验收否决修复共享最多三次修改。
9. Human 结果忠实展示 Worker 状态、指标、行为事实和完整源码，不调用 Designer、Repair 或 Acceptance Agent。
10. 前端自动轮询运行状态，通过 URL 中的 `run_id` 打开运行，并在策略工作区展示和下载 Human 与三个 Designer 的完整源码。

Backend 的运行状态保存在进程内存中。Backend 重启后不能继续查询旧 Forge Run；Worker 的日志和结果文件保存在 `lean_worker/workspace/`。

## 当前进度（2026-07-23）

- React 前端、FastAPI Backend、真实本地 LEAN Worker 和四个公共基线已经接通。
- DeepSeek Designer、Repair、Acceptance 闭环已经接通；API Key 只通过根目录 `.env` 注入。
- Hybrid 基线此前会保留已经退出候选池的旧仓位，再叠加新目标仓位，造成总目标超过购买力；失败后还可能撤销已经处于 `Invalid` 的订单。共享调仓器和 Hybrid 策略现已修复这两条路径。
- 共享调仓器会把目标总仓位限制在 95%，按最小报价单位向下对齐买入限价，并且不再撤销终态订单。Hybrid 会明确卖出落选持仓、在交易成本过滤后重新限制总仓位，并把同日多个止损合并为一次调仓。
- Hybrid 的信号/最小方差权重从 42.5%/57.5% 调整为 70%/30%，仍保留协方差分散，但在当前实验区间提高了风险调整后表现。

验收记录：

| Worker Run | 股票池 | 状态 | CAGR | Sharpe | 最大回撤 | 拒单 |
|---|---:|---|---:|---:|---:|---:|
| `20260723-061822-624705de` | 5 | completed | 27.418% | 1.030 | 18.7% | 0 |
| `20260723-061912-b436de9c` | 30 | completed | 15.476% | 0.585 | 20.7% | 0 |

两次验收均使用 2020-01-02 至 2024-12-31、初始资金 100,000 美元、SPY benchmark、10 bps 交易费和 5 bps 滑点。30 股票运行用于完整目录兼容性检查，不代表其收益一定优于更集中的候选池。

旧 Forge Run `forge-96e7de2ab08d` 的历史状态不会被原地改写，因此前端仍会如实显示该次运行失败及其诊断指标。要让 Baseline Comparison 展示修复后的 `completed` 结果，需要在前端新建一次 Forge Run。

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

所有策略从 `AlphaForgeBaseAlgorithm` 继承固定的 2% LEAN 购买力缓冲。Designer 模板还提供内部 `target_gross = 0.95`，要求候选的目标绝对仓位总和不超过 95%。Designer 不设统一单标的仓位上限；单股集中度由每个策略自己设计。`target_gross` 是内部执行默认，不是前端字段。

## DeepSeek 上下文

Backend 使用 `.env` 中的 `API_KEY`、`BASE_URL`、`MODEL` 和 `THINKING_ENABLED`，通过 OpenAI Python SDK 调用兼容的 DeepSeek Chat Completions API。

每次 Designer 请求按以下顺序组织：

1. system prompt；
2. 可运行的 `UserStrategy` QuantConnect Python 模板；
3. `docs/lean/text/alphaforge-python-v1/writing-algorithms-python.txt` 的完整纯文本内容；
4. Designer 类型、RunSettings、四个公共基线结果；
5. 输出要求：一个 JSON 对象，其中只有完整的 `source_code`。

三个首次设计请求互相独立并同时发出。候选回测失败时，Repair 请求仍按模板、完整原文文档、动态修复请求的顺序组织；动态部分包含完整候选源码、Worker 结果和完整 LEAN 控制台日志。发送内容不包含 API Key、本地路径、Git 信息、源码哈希或 Worker 实现。

Acceptance Agent 只在 Worker 返回 `completed` 后调用。它不接收 LEAN 文档、QC 模板或基线结果；上下文由固定 A1–A5 规则、轨道要求、RunSettings、完整候选源码、完整 Worker 结果、完整控制台日志、精确行为事实和验收轮次组成。A1 要求至少一笔成交、至少一个非零持仓快照和正的最大总敞口。A1–A5 全部通过才接受候选，收益和风险指标不属于验收条件。

Designer 模板给出两种 History DataFrame 范式：单标的使用普通 `history(TradeBar, ...)`，多标的使用 `af_split_history_frames(history(...))`。`history[TradeBar](...)` 返回对象序列，不能作为 pandas DataFrame 下标访问。日线 long-only 组合使用 `af_rebalance_to_weights`，由共享基类等待减仓成交后再按新价格计算买单。

## API

Backend：

- `GET /v1/health`
- `GET /v1/catalog/universe`
- `GET /v1/catalog/baselines`
- `POST /v1/forge-runs`，请求体包含 `settings` 和 `human_strategy`
- `GET /v1/forge-runs/{run_id}`

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
3. 写入本次任务的 Python 文件；
4. 交给真实 LEAN Python 引擎加载和执行；
5. 从 LEAN 控制台提取运行状态和四项摘要指标，并保留完整日志；订单、持仓、敞口和调仓明细通过只读 details 接口供 Backend 构造验收事实。

Worker 不做 Python 包黑名单、AST 准入、源码关键词过滤或 import 过滤。NumPy、pandas、scikit-learn、SciPy、XGBoost 和 LightGBM 可以被策略直接导入。Python 或 LEAN 错误会作为该候选的真实失败结果返回。

Worker `result.json` 只包含 `run_id`、`status`、四项 `summary` 和 `errors`。完整控制台日志保存在对应结果目录。

## 测试

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
PYTHONPATH=frontend .venv/bin/python -m pytest frontend/tests -q
PYTHONPATH=lean_worker .venv/bin/python -m pytest lean_worker/tests -q
```

机器学习和深度学习相关的本地实验环境使用 conda `ml_env`；金融学相关实验使用 `fin_env`。Docker 中的 LEAN Worker 使用自身固定的 Python 环境。
