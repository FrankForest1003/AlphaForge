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
4. Backend 把四个基线的四项摘要指标同时交给三个 Designer，并在等待响应期间提交 Human 策略。Human 源码、设置和结果不会进入任何 AI 上下文。
5. 三个 Designer 各自返回结构化 `design` 和完整 `source_code`；Backend 先进行确定性的 AST/源码预检，通过后 Worker 才串行运行候选策略。
6. 静态预检或候选回测失败时，Backend 按稳定错误分类调用 Repair Agent；Repair 只修复第一个中断阶段并输出修改摘要。
7. Designer 候选运行成功时，Backend 从 Worker 明细构造订单、持仓、敞口和调仓事实，并由 Acceptance Agent 检查 A1 实际投资行为、A2 数据到订单因果链、A3 轨道完整性、A4 时间完整性和 A5 共享设置。
8. 验收否决时，完整验收报告进入 Repair；修复后的完整源码重新回测并重新验收。运行错误修复与验收否决修复共享最多三次修改。
9. Human 结果忠实展示 Worker 状态、指标、行为事实和完整源码，不调用 Designer、Repair 或 Acceptance Agent。
10. 前端自动轮询运行状态，通过 URL 中的 `run_id` 打开运行；`AI Forge` 页面展示公开证据、独立设计、静态验证、LEAN 回测和验收五个阶段，`Results` 与 `Strategy Code` 页面分别提供横向比较和源码查看。

Backend 的普通运行状态保存在进程内存中。每次 Designer、Repair 和 Acceptance 调用另有独立的持久化 Agent Trace，保存在 `backend/workspace/forge_traces/`；Backend 重启后仍可通过 Trace 接口读取。Worker 的日志和结果文件保存在 `lean_worker/workspace/`。

## 当前进度（2026-07-23）

- React 前端、FastAPI Backend、真实本地 LEAN Worker 和四个公共基线已经接通。
- DeepSeek Designer、Repair、Acceptance 闭环已经接通；API Key 只通过根目录 `.env` 注入。
- Designer 与 Repair 已从“整本 LEAN 文档注入”改为版本化的紧凑能力契约、轨道配方和可运行模板；Designer 同时产出策略论点、信号、特征、训练计划、选择规则、风控和因果链。
- AI 候选在进入 Worker 前必须通过确定性预检。预检会拦截不安全 import、错误 History 调用、低层 `DMatrix`、绕过共享调仓器、缺少共享设置以及 Traditional/ML/Hybrid 轨道不完整等问题。
- 预检契约已升级到 v2：额外检查 LEAN schedule 重载、`af_record_ml_*` 单字典签名和字段、透明信号记录、必然不可达的负 `iloc` 分支及未来标签填零。
- Repair 会收到静态诊断或运行错误的稳定分类、行为证据和首个中断阶段；空响应或无效 JSON 会用更保守的参数自动重试一次。
- Worker Trace 继续保留完整日志；Agent 只接收有上限的关键摘录，Acceptance 12,000 字符、Repair 20,000 字符，防止逐日 debug 再次制造超长上下文。
- DeepSeek 漏掉 JSON 最外层结束符时，Backend 会恢复已经完整返回的结构化设计和源码；恢复结果仍需通过全部静态预检。Agent 覆盖基类 `af_*` 方法会被拒绝。
- 每轮验收现在区分 evidence-only、strategy behavior change 和 ineffective。验收通过只代表可运行与可审计，PK 胜负依据 Sharpe、CAGR、最大回撤单独决定。
- `PK Arena` 把最近五次 Forge Run 作为 Best-of-Five 对局持久化展示，可展开每轮三个 AI 候选和全部 Review；Human 历史只保存在独立 UI 历史文件中，不会进入 Agent Trace 或提示词。
- React 已增加 `AI Forge` 五阶段工作区和明确的 `User Strategy Hidden From AI` 信息边界；设计证据、预检结果、修复沿革和 token 使用均可在候选卡片中查看。
- 真实 ML Designer 烟雾测试把 prompt tokens 从历史约 217,557 降到 2,413；生成结果包含完整结构化设计，并一次通过静态预检。该结果只验证生成协议，最终可运行性仍以 LEAN 和 Acceptance 为准。
- Backend 按轮次持久化 DeepSeek 请求中的动态上下文、SDK 原始响应、原始响应文本、解析结果、token usage、错误和耗时，并把每版候选源码与对应 Worker 结果、完整日志、行为事实及验收报告关联起来。
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
| `symbols` | 用户勾选的股票候选池，5–30 只 |
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
2. 版本化的紧凑能力契约和对应 Traditional/ML/Hybrid 轨道配方；
3. 可运行的 `UserStrategy` QuantConnect Python 模板；
4. RunSettings 和四个公共基线结果；
5. 结构化输出协议：`design` 加完整 `source_code`。

官方 LEAN 文档仍会在启动时做资源健康检查，但不再整本注入每个请求。历史 Trace 中 Designer 单次提示约为 21.8 万 token、Repair 约为 22.3–22.4 万 token，这是上下文稀释和成本失控的主要来源之一。紧凑契约只保留项目实际支持的 API、常见 LEAN 陷阱、稳定 ML 子集、证据钩子和七项自检。

三个首次设计请求互相独立并同时发出。静态预检不通过、回测失败或 Acceptance 否决时，Repair 收到当前设计、完整源码、预检报告、稳定失败分类及相关运行证据；它必须说明修改内容和首个中断阶段。发送内容不包含 API Key、本地路径、Git 信息、Worker 实现或任何 Human 策略信息。

Acceptance Agent 只在 Worker 返回 `completed` 后调用。它不接收 LEAN 文档、QC 模板或基线结果；上下文由固定 A1–A5 规则、轨道要求、RunSettings、完整候选源码、完整 Worker 结果、完整控制台日志、精确行为事实和验收轮次组成。A1 要求至少一笔成交、至少一个非零持仓快照和正的最大总敞口。A1–A5 全部通过才接受候选，收益和风险指标不属于验收条件。

每个 Forge Run 的 Agent Trace 独立于普通运行响应。Trace 保存模型、thinking、token 上限、每次尝试、动态上下文、原始响应、解析 JSON、预检历史、修复沿革和 token usage。Trace 的 context manifest 明确列出可见的公共基线、RunSettings 和 ExperimentContract，同时列出被排除的 Human 源码、设置、结果和教育内容。Trace 不保存 `API_KEY`。它还逐轮关联送入 Worker 的源码、Worker Run ID、运行结果、日志、行为事实和验收报告。

Designer 模板给出两种 History DataFrame 范式：单标的使用普通 `history(TradeBar, ...)`，多标的使用 `af_split_history_frames(history(...))`。`history[TradeBar](...)` 返回对象序列，不能作为 pandas DataFrame 下标访问。日线 long-only 组合使用 `af_rebalance_to_weights`，由共享基类等待减仓成交后再按新价格计算买单。

## API

Backend：

- `GET /v1/health`
- `GET /v1/catalog/universe`
- `GET /v1/catalog/baselines`
- `POST /v1/forge-runs`，请求体包含 `settings` 和 `human_strategy`
- `GET /v1/forge-runs/{run_id}`
- `GET /v1/forge-runs/{run_id}/trace`，返回可跨 Backend 重启读取的完整 Agent 复盘记录
- `GET /v1/forge-history`，返回最近五轮 Human vs AI PK 历史
- `GET /v1/forge-history/{run_id}`，返回指定历史轮次详情

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

Worker 本身仍是可信执行边界，不做源码准入；但 Backend 现在会在 AI 候选提交 Worker 前执行确定性 AST/源码预检。当前 AI 稳定路径允许 NumPy、pandas 和 scikit-learn，禁止低层 XGBoost `DMatrix`、直接 `SetHoldings`/`Liquidate`、动态执行和文件访问。Human 代码模式保持独立的现有检查与执行路径。

Worker `result.json` 只包含 `run_id`、`status`、四项 `summary` 和 `errors`。完整控制台日志保存在对应结果目录。

## 测试

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
PYTHONPATH=frontend .venv/bin/python -m pytest frontend/tests -q
PYTHONPATH=lean_worker .venv/bin/python -m pytest lean_worker/tests -q
```

机器学习和深度学习相关的本地实验环境使用 conda `ml_env`；金融学相关实验使用 `fin_env`。Docker 中的 LEAN Worker 使用自身固定的 Python 环境。
