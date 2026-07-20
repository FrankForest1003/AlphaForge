# AlphaForge 软件原型与接口方案 v0.2

> **项目名称：** AlphaForge — A Risk-Aware Multi-Agent Platform for Automated Trading Strategy Optimization  
> **文档用途：** 明确软件原型的页面、功能、状态、后端接口和最小可行实现范围  
> **版本日期：** 2026-07-20  
> **当前定位：** 面向学习、研究与决策支持的策略优化与回测平台，不提供真实交易下单服务  
> **建议技术栈：** Streamlit 前端 + FastAPI 主服务 + 独立 LEAN Worker + 本地文件/SQLite 存储

## 0. 当前真实进度与本版调整

截至 2026-07-20，团队已大致跑通多智能体编排主流程：

```text
Strategy + Baselines
→ Evidence Summary
→ Traditional / ML / Hybrid Designer
→ Spec Builder
→ QC Code Agent
→ Static Check
→ Code Risk Agent
→ LEAN Smoke Test
→ Backtest
→ Post-Backtest Analysis Agent
→ Candidate Selector
→ Result
```

其中 `Static Check`、`Code Risk Agent` 和 `LEAN Smoke Test` 的失败结果可以进入 `Repair Agent`，修复后必须回到检查节点重新验证。

本进度应准确表述为：**Agent orchestration 已跑通或已完成 Mock/局部联调，但 AlphaForge DSL 与真实 LEAN Backtest Engine 尚未完成端到端接入。** 在 DSL 和真实引擎接入以前，不应把整个系统标记为 E2E completed。

当前开发主线因此调整为：

1. 冻结 AlphaForge DSL v1；
2. 将三个 Designer 的输出统一转换成合法 DSL；
3. 建立 `DSL → QC Python` 的受控编译接口；
4. 将 Smoke Test 与 Full Backtest 接入独立 LEAN Worker；
5. 将真实结果送入 Post-Backtest Analysis 和 Candidate Selector；
6. 前端展示每个节点的真实状态、输入摘要、输出产物和失败原因。

### 0.1 对当前编排图的命名和连线调整建议

当前编排逻辑基本合理，但正式架构图和代码节点建议统一如下：

- `Spec Builder` 改名为 `DSL Builder + Validator`；
- `QC Code Agent` 优先改名为 `DSL-to-QC Compiler`，若暂时仍使用 LLM，则标注 `Constrained Code Generator`；
- `LEAN Smoke Test` 与 `Backtest` 之间增加条件 `smoke_passed = true`；
- Repair Agent 的回线明确回到 `Static Check`，不要画成可直接返回 Smoke 或 Backtest；
- `Backtest` 输出先进入 `Normalized Result Parser`，再交给 `Post-Backtest Analysis Agent`；
- `Candidate Selector` 应同时接收三个候选的真实结果以及用户策略/基线证据；
- `Result` 应允许 `recommended_candidate` 为空，并输出 `No Robust Improvement Found`；
- 图例中将 `LEAN Execution` 改为 `Execution / Engine`，并把结果解析器标为确定性模块。

建议正式主链为：

```text
Designers → DSL Builder/Validator → DSL-to-QC Compiler
→ Static Check → Code Risk Check → LEAN Smoke
→ Full Backtest → Result Parser → Post-Backtest Analysis
→ Candidate Selector → Recommendation / No Improvement
```

---

## 1. 原型要回答的核心问题

AlphaForge 的软件原型必须让用户看懂并完成以下闭环：

1. 我想优化什么股票池、时间段和初始策略；
2. 我的策略和四个基线策略表现如何；
3. 多智能体发现了哪些问题、提出了哪些有约束的改进；
4. 三类候选策略——Traditional、ML、Hybrid——分别是什么；
5. 候选策略是否通过结构、风险和代码验证；
6. 候选策略在同一 LEAN 环境下是否真的优于原策略和基线；
7. 如果没有稳健提升，系统应明确输出 **No robust improvement found**，而不是强行推荐策略。

### 1.1 推荐的主交互形式

采用一个五步式项目工作台：

```text
Step 1 项目配置
    ↓
Step 2 基线回测
    ↓
Step 3 AI 优化
    ↓
Step 4 候选验证与 LEAN 回测
    ↓
Step 5 对比报告与最终结论
```

左侧导航只保留：

- `Projects`：创建、打开和管理项目；
- `Workspace`：当前项目的五步主流程；
- `Runs`：回测与优化任务记录；
- `System`：LEAN Worker、数据和模型服务状态。

这样既像真正的软件，也不会让课堂展示时频繁跳页。

---

## 2. 用户角色与权限边界

MVP 只实现单用户研究模式，不做复杂登录和权限系统。

用户可以：

- 选择 5–30 只白名单股票；
- 设置回测时间、初始资金和基准；
- 选择内置策略或上传/粘贴 QC Python 策略；
- 启动基线回测和优化任务；
- 查看 Agent 分析、AlphaForge DSL、生成代码和回测结果；
- 下载报告、DSL JSON、LEAN Python 代码和结果文件。

用户不可以：

- 直接连接券商或提交真实订单；
- 让 LLM 执行任意系统命令；
- 绕过股票池、风险上限和 DSL 校验；
- 修改已完成任务的原始结果。

---

## 3. 信息架构与页面清单

| 编号 | 页面/区域 | 主要目的 | MVP |
|---|---|---|---|
| P0 | Projects 项目首页 | 创建、打开、复制项目 | 必须 |
| P1 | Setup 项目配置 | 定义股票池、时间、资金、策略和风险偏好 | 必须 |
| P2 | Baselines 基线回测 | 运行用户策略与四个基线，统一查看结果 | 必须 |
| P3 | AI Optimization 优化工作台 | 展示真实 Agent 编排、修复回路和三个候选 DSL | 必须 |
| P4 | Candidate Lab 候选验证 | 查看 DSL、验证门、生成代码和 LEAN 执行状态 | 必须 |
| P5 | Comparison Report 对比报告 | 比较指标、鲁棒性和最终推荐 | 必须 |
| P6 | Runs 任务中心 | 查看所有异步任务、日志、失败原因和产物 | 建议 |
| P7 | System 系统状态 | 检查 API、LEAN、数据覆盖和 LLM 状态 | 必须 |
| P8 | Admin/用户管理 | 登录、权限、配额 | 不做 |
| P9 | Live Trading | 实盘交易 | 不做 |

---

## 4. 各页面的具体方案

## 4.1 P0 — Projects 项目首页

### 页面目标

管理一次完整的策略优化实验。一个 Project 包含配置、任务、策略、结果和报告。

### 页面布局

- 顶部：项目名称、项目说明、`New Project` 按钮；
- 中部：项目卡片列表；
- 卡片字段：状态、股票数、回测区间、当前步骤、最后更新时间；
- 操作：`Open`、`Duplicate`、`Archive`。

### 核心功能

- 创建空白项目；
- 从预置 Demo 创建项目；
- 打开未完成项目继续运行；
- 查看最近一次任务状态。

### 对应接口

- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `POST /api/v1/projects/{project_id}/duplicate`

---

## 4.2 P1 — Setup 项目配置

### 页面目标

收集一个可复现回测任务所需的全部输入，并在提交前完成校验。

### 页面区域 A：Universe & Period

- 股票池：从 30 只白名单中多选，限制 5–30 只；
- 回测开始日期和结束日期；
- 频率：MVP 固定 `Daily`；
- 市场：MVP 固定 `US-listed equities`；
- 基准：默认 `SPY`；
- 初始资金：默认 `100,000 USD`。

### 页面区域 B：User Strategy

提供两种输入方式：

1. `Built-in Template`：选择系统内置策略；
2. `QC Python Code`：粘贴或上传一个 `main.py`。

MVP 不要求系统理解任意用户 Python 的全部语义。上传代码只用于 LEAN 回测；如果要进入结构化优化，必须同时选择一个可识别模板或提供合法的 AlphaForge DSL。

### 页面区域 C：Risk Preferences

- 最大允许回撤，例如 25%；
- 单股最大权重，例如 35%；
- 是否允许做空：MVP 固定为否；
- 是否允许杠杆：MVP 固定为否；
- 调仓频率：MVP 固定为每月；
- 选择数量：默认 Top 3；
- 优化偏好：`Balanced`、`Return-Oriented`、`Risk-Oriented`。

优化偏好只改变评分权重，不得取消硬性风险约束。

### 页面区域 D：Preflight Check

用户点击 `Validate Configuration` 后显示：

- 参数是否合法；
- 所需行情数据是否存在；
- map/factor 文件是否齐全；
- 用户策略能否加载；
- LEAN Worker 是否在线；
- 预计会运行多少个任务。

只有 Preflight 通过后，`Run Baselines` 才可用。

### 对应接口

- `GET /api/v1/catalog/universe`
- `GET /api/v1/catalog/strategy-templates`
- `PUT /api/v1/projects/{project_id}/configuration`
- `POST /api/v1/projects/{project_id}/preflight`

---

## 4.3 P2 — Baselines 基线回测

### 页面目标

在相同数据、成本、时间范围和 LEAN 版本下，运行：

- User Strategy；
- Traditional Baseline 1；
- Traditional Baseline 2；
- ML Baseline 1；
- ML Baseline 2。

### 页面布局

上方为五张任务卡，每张卡显示：

- `Queued / Running / Succeeded / Failed`；
- 当前阶段，如 `Preparing Data`、`LEAN Running`、`Parsing Result`；
- 执行时间；
- `View Log` 与 `Retry`。

下方为统一结果表：

| Strategy | Type | CAGR | Sharpe | Sortino | MDD | Volatility | Turnover | Fees | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|

并展示：

- Equity Curve；
- Drawdown Curve；
- Monthly Return Heatmap；
- 关键诊断提示，例如高回撤、高换手或表现不稳定。

### 关键交互

- `Run All`：一次提交五个任务；
- `Retry Failed`：只重跑失败任务；
- `Continue to AI Optimization`：五个结果至少有用户策略和四基线中的三个成功后开放；
- 如果某个结果失败，必须展示明确错误类型，不显示虚构指标。

### 对应接口

- `POST /api/v1/projects/{project_id}/baseline-runs`
- `GET /api/v1/run-groups/{run_group_id}`
- `GET /api/v1/backtest-runs/{run_id}`
- `GET /api/v1/backtest-runs/{run_id}/result`
- `POST /api/v1/backtest-runs/{run_id}/retry`

前端 MVP 每 2–3 秒轮询任务状态，不必立即实现 WebSocket。

---

## 4.4 P3 — AI Optimization 优化工作台

### 页面目标

让用户理解“Agent 为什么提出这些修改”，同时避免展示冗长的内部思维过程。

### 页面区域 A：Optimization Controls

- 最大候选数：MVP 固定 3；
- 候选类型：Traditional、ML、Hybrid 各一个；
- 最大优化轮数：建议 1–2；
- 评分偏好：从项目配置读取；
- `Start Optimization` 按钮。

### 页面区域 B：Agent Pipeline

前端节点必须与实际 Orchestrator 一一对应，不再使用泛化的 Analyst/Reviewer 占位名称：

1. `Evidence Summary`：把用户策略和四个基线结果转换为统一证据；
2. `Traditional Designer`：提出纯传统候选；
3. `ML Designer`：提出纯 ML 候选；
4. `Hybrid Designer`：提出传统与 ML 混合候选；
5. `DSL Builder`：把三个 Designer 输出标准化为 AlphaForge DSL；
6. `QC Code Generator`：从合法 DSL 生成 QC Python；
7. `Static Check`：执行语法、导入、API allowlist 和确定性检查；
8. `Code Risk Agent`：检查未来数据泄漏、风险绕过和危险代码模式；
9. `LEAN Smoke Test`：使用短区间验证算法能否启动和完成；
10. `Full Backtest`：执行统一期间的完整回测；
11. `Post-Backtest Analysis Agent`：分析真实结果和鲁棒性证据；
12. `Candidate Selector`：依据硬门槛和评分公式选择或拒绝候选。

`Repair Agent` 是失败分支而不是正常主链节点。它只能接收：

- Static Check failure；
- Code Risk finding 中允许修复的兼容问题；
- LEAN Smoke Test 的编译、导入、类型或 API 兼容错误。

修复后必须回到 `Static Check`，不得直接跳到 Full Backtest；每个候选最多自动修复 2 次。Repair Agent 不得修改 DSL 所表达的信号、选股、权重、调仓和风险语义。

每个节点只展示结构化摘要：

- Inputs；
- Findings；
- Proposed Changes；
- Decision；
- Evidence References；
- Artifact ID；
- Started/Finished Time；
- Retry Count。

不显示大模型隐藏推理链，也不允许 Agent 直接修改 LEAN 运行环境。

### 页面区域 C：Candidate Cards

三个候选卡片分别显示：

- 候选名称和类型；
- 一句话策略逻辑；
- 相比用户策略改变了什么；
- 预期改善的风险或表现；
- 风险审查状态；
- DSL 验证状态；
- Static / Risk / Smoke / Full Backtest 四个验证门状态；
- `Open Candidate`。

### 对应接口

- `POST /api/v1/projects/{project_id}/optimization-runs`
- `GET /api/v1/optimization-runs/{optimization_id}`
- `GET /api/v1/optimization-runs/{optimization_id}/events`
- `GET /api/v1/optimization-runs/{optimization_id}/candidates`
- `POST /api/v1/optimization-runs/{optimization_id}/resume`
- `POST /api/v1/optimization-runs/{optimization_id}/cancel`

---

## 4.5 P4 — Candidate Lab 候选验证与回测

### 页面目标

把 DSL、验证门、生成代码、修复记录和 LEAN 结果放在一个页面中，形成可审计证据链。

### 顶部候选切换

- `C-T Traditional`
- `C-ML Machine Learning`
- `C-H Hybrid`

### Tab 1：Overview

- 候选策略摘要；
- 关键改动；
- 使用的信号、选股、权重和风险模块；
- 与原策略的差异列表；
- 风险审查结论。

### Tab 2：AlphaForge DSL

- 格式化 JSON 查看器；
- `dsl_version` 与 DSL 哈希；
- JSON Schema 状态；
- 语义验证状态；
- 风险硬约束状态；
- 数据需求检查状态；
- Designer 原始提案与 DSL 的映射差异；
- `Download JSON`。

### Tab 3：Generated LEAN Code

- 只读代码查看器；
- 对应 DSL 哈希；
- 代码哈希；
- 编译器/生成器版本；
- 静态检查结果；
- Code Risk 检查结果；
- `Download main.py`。

推荐把当前 `QC Code Agent` 收敛为受约束的 `DSL-to-QC Compiler`：优先使用确定性模板和组件组合；如果保留 LLM 参与，只允许它填写受控代码槽位，并必须通过静态检查、风险检查和 Smoke Test。候选的 DSL 哈希在修复前后必须保持一致，否则修复无效并退回人工检查。

### Tab 4：Backtest

- `Run Smoke Test` 与 `Run Full Backtest` 分开显示；
- Worker、LEAN 和 Python 版本；
- 数据 manifest、任务进度与最近日志；
- 成功后显示标准化指标和曲线；
- 失败时显示错误分类、失败节点和有限次数的修复记录；
- 显示 `DSL hash → code hash → run id → result hash` 追踪链。

修复只能处理 API 名称、导入、类型或模板兼容问题，不得静默改变策略语义。

### 对应接口

- `GET /api/v1/candidates/{candidate_id}`
- `GET /api/v1/candidates/{candidate_id}/dsl`
- `POST /api/v1/candidates/{candidate_id}/dsl/build`
- `POST /api/v1/candidates/{candidate_id}/dsl/validate`
- `POST /api/v1/candidates/{candidate_id}/compile`
- `GET /api/v1/candidates/{candidate_id}/code`
- `POST /api/v1/candidates/{candidate_id}/smoke-runs`
- `POST /api/v1/candidates/{candidate_id}/backtest-runs`
- `GET /api/v1/candidates/{candidate_id}/lineage`
- `GET /api/v1/candidates/{candidate_id}/repairs`

---

## 4.6 P5 — Comparison Report 对比报告

### 页面目标

用统一证据回答：优化策略是否真的更好，以及改善是否值得承担额外复杂度。

### 页面区域 A：Final Decision

最终状态只能是：

- `Recommended`：通过全部门槛且具有稳健改善；
- `Conditionally Recommended`：有改善，但存在清楚标注的限制；
- `No Robust Improvement Found`：没有候选同时满足性能和风险要求。

### 页面区域 B：Strategy Comparison

比较对象：用户策略、四个基线和三个候选。

建议图表：

- 风险—收益散点图；
- Equity Curve；
- Drawdown Curve；
- 指标对比表；
- 候选相对用户策略的变化百分比。

主要指标：

- CAGR；
- Sharpe；
- Sortino；
- Maximum Drawdown；
- Annualized Volatility；
- Turnover；
- Fees；
- Total Orders。

### 页面区域 C：Robustness Evidence

MVP 至少选择一种：

- Train/Test 时间切分；或
- 不同市场阶段子区间；或
- 参数轻微扰动测试。

不可只根据全样本 Sharpe 选胜者。

### 页面区域 D：Explainability & Download

- 推荐或拒绝理由；
- 风险警告；
- 从原策略到候选策略的结构化改动；
- 下载 HTML/JSON 报告、AlphaForge DSL、LEAN 代码和运行清单。

### 对应接口

- `POST /api/v1/projects/{project_id}/reports`
- `GET /api/v1/projects/{project_id}/comparison`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/download?format=json|html`

---

## 4.7 P6 — Runs 任务中心

### 页面目标

方便开发调试，也使软件看起来像真实的异步计算平台。

### 功能

- 按项目、任务类型和状态筛选；
- 查看开始时间、结束时间和耗时；
- 查看结构化日志；
- 查看任务使用的代码哈希、配置哈希、LEAN 版本和数据清单；
- 对失败任务执行重试；
- 下载原始与标准化结果。

### 对应接口

- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/logs`
- `GET /api/v1/runs/{run_id}/artifacts`

---

## 4.8 P7 — System 系统状态

### 页面目标

在演示和开发前快速判断环境是否可用。

### 状态卡

- FastAPI：Online/Offline；
- LEAN Worker：Online/Busy/Offline；
- LEAN 版本；
- Python 版本；
- LLM Provider：Ready/Unavailable；
- 数据覆盖：股票数量、起止日期、缺失文件；
- 最近一次 Smoke Test 状态。

### 对应接口

- `GET /api/v1/health`
- `GET /api/v1/system/capabilities`
- `GET /api/v1/workers`
- `GET /api/v1/data/coverage`
- `POST /api/v1/system/smoke-test`

---

## 5. 页面与接口总映射

| 页面 | 读取接口 | 写入/执行接口 |
|---|---|---|
| Projects | `GET /projects`、`GET /projects/{id}` | `POST /projects`、`POST /projects/{id}/duplicate` |
| Setup | `GET /catalog/*` | `PUT /projects/{id}/configuration`、`POST /projects/{id}/preflight` |
| Baselines | `GET /run-groups/{id}`、`GET /backtest-runs/{id}/result` | `POST /projects/{id}/baseline-runs`、`POST /backtest-runs/{id}/retry` |
| AI Optimization | `GET /optimization-runs/{id}`、`GET .../events` | `POST /projects/{id}/optimization-runs` |
| Candidate Lab | `GET /candidates/{id}/dsl|code|lineage|repairs` | `POST /dsl/build`、`POST /dsl/validate`、`POST /compile`、`POST /smoke-runs`、`POST /backtest-runs` |
| Comparison | `GET /projects/{id}/comparison`、`GET /reports/{id}` | `POST /projects/{id}/reports` |
| Runs | `GET /runs`、`GET /runs/{id}/logs` | Retry 类操作 |
| System | `GET /health`、`GET /workers`、`GET /data/coverage` | `POST /system/smoke-test` |

所有正式路径统一添加 `/api/v1` 前缀。

---

## 6. MVP 核心数据结构

## 6.1 Project Configuration

```json
{
  "name": "AlphaForge Demo",
  "universe": ["AAPL", "MSFT", "NVDA", "JPM", "COST"],
  "start_date": "2018-01-01",
  "end_date": "2025-12-31",
  "resolution": "daily",
  "benchmark": "SPY",
  "initial_cash": 100000,
  "strategy_input": {
    "mode": "template",
    "template_id": "monthly_momentum_v1"
  },
  "constraints": {
    "long_only": true,
    "leverage_allowed": false,
    "rebalance": "monthly",
    "top_k": 3,
    "max_position_weight": 0.35,
    "max_drawdown": 0.25
  },
  "objective_profile": "balanced"
}
```

## 6.2 AlphaForge DSL v1

DSL 是整个系统的中心合同：Designer 不直接把自然语言交给代码生成器，LEAN 也不直接执行 Agent 的自由文本。三个候选都必须先成为同一结构的 DSL 文档。

DSL v1 建议只覆盖团队能够真实生成和回测的策略空间：日频、美国上市大盘股、long-only、每月调仓、Top-K 选择、无杠杆。不要为了“通用”提前加入期权、分钟级、做空和任意 Python 表达式。

```json
{
  "dsl_version": "1.0.0",
  "candidate_id": "candidate_hybrid_001",
  "candidate_type": "hybrid",
  "universe": {
    "source": "project_universe",
    "asset_class": "us_equity",
    "resolution": "daily"
  },
  "features": [
    {"id": "mom_63", "type": "momentum", "lookback_days": 63},
    {"id": "sma_gap_200", "type": "sma_gap", "lookback_days": 200}
  ],
  "model": {
    "type": "gradient_boosting",
    "target": "next_21d_excess_return",
    "training_window_days": 756,
    "retrain_frequency": "monthly"
  },
  "signal": {
    "type": "weighted_fusion",
    "inputs": ["traditional_score", "ml_score"],
    "weights": [0.85, 0.15]
  },
  "selection": {"method": "rank", "top_k": 3},
  "allocation": {"method": "capped_score_weight", "max_weight": 0.35},
  "risk": {
    "market_filter": {"symbol": "SPY", "type": "sma", "lookback_days": 200},
    "fallback": "cash",
    "max_drawdown": 0.25,
    "long_only": true,
    "leverage_allowed": false
  },
  "rebalance": {"frequency": "monthly"},
  "cost_model": {"fee_model": "lean_default", "slippage_model": "lean_default"},
  "data_requirements": {
    "symbols": "project_universe",
    "requires_factor_files": true,
    "requires_map_files": true,
    "warmup_days": 756
  }
}
```

### DSL 必须执行的四级校验

1. **Schema validation**：字段、类型、枚举和必填项正确；
2. **Semantic validation**：例如 `top_k ≤ universe_size`、权重和为 1、warmup 足够；
3. **Risk validation**：满足 long-only、无杠杆、最大仓位和最大回撤限制；
4. **Capability validation**：当前编译器和 LEAN Worker 确实支持 DSL 中使用的模块。

DSL Schema 必须限制模块枚举、参数范围和必填字段，禁止自然语言、Python 表达式和任意代码进入 DSL。建议新增：

```text
shared/contracts/alphaforge_dsl_v1.schema.json
shared/contracts/dsl_validation_result.schema.json
shared/contracts/candidate_lineage.schema.json
```

## 6.3 Normalized Backtest Result

```json
{
  "run_id": "run_20260720_001",
  "status": "succeeded",
  "strategy_id": "candidate_hybrid_001",
  "period": {"start": "2018-01-01", "end": "2025-12-31"},
  "metrics": {
    "cagr": 0.1468,
    "sharpe": 0.476,
    "sortino": 0.512,
    "max_drawdown": 0.237,
    "volatility": null,
    "turnover": null,
    "fees_usd": 55.15,
    "total_orders": 19
  },
  "environment": {
    "lean_version": "2.5.0.0",
    "python_version": "3.11.11"
  },
  "artifacts": {
    "equity_curve": "artifacts/equity_curve.json",
    "raw_result": "artifacts/lean-result.json",
    "log": "artifacts/lean.log"
  }
}
```

其中示例数值来自已跑通的本地 LEAN 结果，仅用于说明字段格式，不应作为新候选策略结果展示。

## 6.4 Job Status

```json
{
  "run_id": "run_20260720_001",
  "run_type": "backtest",
  "status": "running",
  "stage": "lean_execution",
  "progress": 65,
  "message": "LEAN backtest is running",
  "created_at": "2026-07-20T10:00:00+08:00",
  "updated_at": "2026-07-20T10:01:12+08:00"
}
```

任务状态统一为：

```text
queued → validating → preparing → running → parsing → succeeded
                                            └→ failed
```

Agent 优化任务的 `stage` 使用固定枚举，不允许各 Agent 自由命名：

```text
evidence_summary
traditional_design | ml_design | hybrid_design
dsl_build → dsl_validation → code_generation
→ static_check → code_risk_check → lean_smoke_test
→ full_backtest → post_backtest_analysis → candidate_selection
```

当进入修复分支时，额外记录：

```json
{
  "stage": "repair",
  "failed_stage": "lean_smoke_test",
  "repair_attempt": 1,
  "max_repair_attempts": 2,
  "dsl_hash_before": "sha256:...",
  "dsl_hash_after": "sha256:..."
}
```

`dsl_hash_before` 与 `dsl_hash_after` 必须相同，否则说明 Repair Agent 改变了策略语义，应拒绝该修复。

---

## 7. 主服务与 LEAN Worker 的接口边界

主 FastAPI 不直接在请求线程内运行 LEAN，而是向独立 Worker 提交任务。

### 7.1 主服务 → Worker

`POST /worker/v1/jobs`

```json
{
  "job_id": "run_20260720_001",
  "run_mode": "smoke",
  "algorithm_uri": "artifacts/main.py",
  "configuration_uri": "artifacts/job-config.json",
  "dsl_uri": "artifacts/alphaforge-dsl.json",
  "code_hash": "sha256:...",
  "dsl_hash": "sha256:...",
  "timeout_seconds": 900
}
```

`run_mode` 只允许 `smoke` 或 `full`。Smoke Test 使用短区间和较短超时，只判断可执行性；Full Backtest 使用项目统一期间并生成正式评估指标。Worker 不负责调用 LLM，也不负责选择候选。

### 7.2 Worker → 主服务

MVP 使用主服务轮询：

- `GET /worker/v1/jobs/{job_id}`
- `GET /worker/v1/jobs/{job_id}/result`
- `GET /worker/v1/health`

以后再增加回调或消息队列。Windows Worker 和未来 Linux Worker 应遵循相同接口，避免前端和 Agent 感知操作系统差异。

### 7.3 Worker 的安全和可复现要求

- 每个任务使用独立目录；
- 设置执行超时；
- 只允许预定义 LEAN 启动方式；
- 验证请求中的 DSL 哈希和代码哈希；
- 保存 `strategy_manifest.json`；
- 保存 `alphaforge_dsl.json`；
- 保存 `lean_environment.json`；
- 保存 `backtest_result_normalized.json`；
- 记录代码哈希、配置哈希、LEAN 版本和数据清单；
- 原始市场数据不提交 Git。

---

## 8. 错误类型与前端提示

后端不要只返回 `500 Internal Server Error`，应统一错误结构：

```json
{
  "error": {
    "code": "LEAN_DATA_MISSING",
    "message": "Daily equity data is missing for NVDA on the selected period.",
    "retryable": false,
    "details": {"symbol": "NVDA"}
  }
}
```

MVP 至少区分：

| 错误码 | 含义 | 前端动作 |
|---|---|---|
| `INVALID_CONFIGURATION` | 项目参数非法 | 返回 Setup 修改 |
| `LEAN_WORKER_OFFLINE` | Worker 不在线 | 提示检查 System 页 |
| `LEAN_DATA_MISSING` | 行情/map/factor 数据缺失 | 展示缺失列表 |
| `STRATEGY_LOAD_FAILED` | QC 策略无法加载 | 展示兼容错误 |
| `DSL_SCHEMA_INVALID` | DSL JSON 结构错误 | 阻止代码生成 |
| `DSL_SEMANTIC_INVALID` | DSL 参数组合不成立 | 返回 DSL Builder 修正 |
| `DSL_CAPABILITY_UNSUPPORTED` | 编译器尚不支持某 DSL 模块 | 拒绝候选或更换受支持模块 |
| `RISK_CONSTRAINT_VIOLATION` | 候选违反硬约束 | 标记 rejected |
| `CODE_VALIDATION_FAILED` | 生成代码静态检查失败 | 允许有限修复 |
| `DSL_CODE_HASH_MISMATCH` | 修复过程改变策略语义或产物链不一致 | 停止自动修复 |
| `REPAIR_LIMIT_EXCEEDED` | 自动修复超过 2 次 | 标记失败并人工检查 |
| `LEAN_EXECUTION_FAILED` | LEAN 执行失败 | 展示日志和重试 |
| `RESULT_PARSE_FAILED` | 结果解析失败 | 保留原始产物供调试 |
| `LLM_UNAVAILABLE` | 模型服务不可用 | 不伪造候选结果 |

---

## 9. 推荐仓库结构

```text
alphaforge-platform/
├─ frontend/
│  ├─ app.py
│  ├─ pages/
│  │  ├─ projects.py
│  │  ├─ workspace.py
│  │  ├─ runs.py
│  │  └─ system.py
│  ├─ components/
│  └─ api_client/
├─ backend/
│  ├─ app/main.py
│  ├─ app/api/v1/
│  ├─ app/models/
│  ├─ app/schemas/
│  ├─ app/services/
│  │  ├─ project_service.py
│  │  ├─ backtest_service.py
│  │  ├─ optimization_service.py
│  │  ├─ candidate_service.py
│  │  └─ report_service.py
│  ├─ app/repositories/
│  └─ tests/
├─ agent/
│  ├─ orchestrator/
│  ├─ roles/designers/
│  ├─ roles/code_risk/
│  ├─ roles/repair/
│  ├─ roles/post_backtest/
│  ├─ prompts/
│  ├─ tools/
│  └─ schemas/
├─ strategy_engine/
│  ├─ dsl/
│  │  ├─ schema/
│  │  ├─ builder/
│  │  └─ capability_registry/
│  ├─ validators/
│  ├─ compiler/
│  └─ templates/
├─ qc_strategies/
│  ├─ baselines/traditional/
│  ├─ baselines/ml/
│  └─ smoke/
├─ shared/
│  ├─ contracts/
│  └─ enums/
├─ docs/
│  ├─ api/
│  ├─ architecture/
│  └─ prototype/
└─ docker-compose.yml

alphaforge-lean-worker/
├─ worker_api/
├─ runner/
├─ parser/
├─ adapters/lean/
├─ artifacts/
├─ config/
├─ scripts/
├─ tests/
└─ README.md
```

LEAN Worker 单独成包或仓库，主平台只依赖它的 HTTP contract。

---

## 10. 原型实现优先级

### 当前状态判断

| 模块 | 当前判断 | 下一验收证据 |
|---|---|---|
| Agent Orchestrator | 主流程大致跑通 | 保存一次完整 run 的 event log 与三个 Designer 原始输出 |
| AlphaForge DSL | 待正式接入 | 三类候选均通过同一 DSL Schema、语义、风险和能力校验 |
| 本地 LEAN | 已独立跑通基础策略 | 通过 Worker HTTP API 触发 Smoke 和 Full 两类任务 |
| Agent ↔ LEAN | 尚未端到端接通 | Candidate DSL 能产生真实 run_id 和标准化结果 |
| 前端 | 以实际仓库为准 | 能展示真实 pipeline stage，而非固定动画或假进度 |

## Phase UI-1：可点击静态原型

- 完成 Projects、Setup、Baselines、AI Optimization、Candidate Lab、Comparison、System 的 Streamlit 页面；
- 使用固定 JSON 假数据；
- 所有按钮、Tab、状态卡和图表可以操作；
- 页面明确标记 `Demo Data`，避免把假数据当成实验结果。

**验收：** 能完整演示用户从新建项目到查看比较报告的流程。

## Phase API-1：FastAPI 合同与 Mock 服务

- 建立 Pydantic 请求/响应模型；
- 实现 health、projects、configuration、runs、candidates、reports 的 Mock API；
- 自动生成 OpenAPI 文档；
- 前端不再直接读取本地固定 JSON，而是调用 API。

**验收：** 前后端分离，错误响应格式统一。

## Phase LEAN-1：真实基线闭环

- 接入 Windows LEAN Worker；
- Preflight 检查真实数据；
- 提交一个真实 baseline job；
- 解析并返回标准化结果；
- 在 Baselines 页面显示真实指标和曲线。

**验收：** 浏览器点击运行后，LEAN 完成任务并把结果返回前端。

## Phase AI-1：Agent Orchestrator 固化（当前大致完成）

- 固定图中实际节点名称和执行顺序；
- 为每个节点定义输入、输出和错误 schema；
- 保存 Traditional、ML、Hybrid Designer 三份原始候选；
- 为 Repair Agent 添加失败来源、最大次数和回跳规则；
- 生成一次可重放的完整 `optimization_run` event log。

**验收：** 重启服务后可以用持久化事件还原一次运行过程；失败节点和修复次数可追踪。

## Phase DSL-1：冻结 AlphaForge DSL v1（当前最高优先级）

- 冻结 `alphaforge_dsl_v1.schema.json`；
- 建立 Traditional、ML、Hybrid 三类合法示例和非法反例；
- 实现 Schema、Semantic、Risk、Capability 四级校验；
- 将三个 Designer 输出统一映射到 DSL；
- 建立 DSL hash 和版本迁移规则；
- 为 DSL 编写单元测试。

**验收：** 三种候选可以稳定生成合法 DSL；非法参数、未来数据泄漏配置和不支持模块能被明确拒绝。

## Phase Compiler-1：DSL 到 QC Python

- DSL 转换为 QC Python；
- 建立受支持模块 registry 和确定性模板；
- 输出代码时写入 DSL hash、compiler version 和 code hash；
- 完成 Static Check 与 Code Risk Check；
- Repair Agent 只能修复代码兼容性并保持 DSL hash 不变。

**验收：** 对相同 DSL 和相同编译器版本重复生成代码时，输出一致；生成代码通过静态和风险检查。

## Phase Engine-1：LEAN Worker 接入

- 实现 `/worker/v1/jobs`、状态、结果和 health 接口；
- 区分 Smoke Test 与 Full Backtest；
- 检查数据覆盖和 warmup；
- 解析 LEAN 原始结果为统一 JSON；
- 将失败错误映射为平台错误码；
- 回传环境、数据、代码和结果哈希。

**验收：** 主平台提交候选后获得真实 run_id；Smoke 成功后才能启动 Full Backtest。

## Phase E2E-1：真实候选闭环与比较报告

- 三候选真实回测；
- 将标准化结果送入 Post-Backtest Analysis Agent；
- Candidate Selector 先执行硬门槛，再执行综合评分；
- 生成统一比较和最终结论；
- 保存完整实验清单。

**验收：** 可复现一次端到端演示；没有稳健提升时能够诚实拒绝推荐。

---

## 11. 四人近期原型任务建议

| 成员 | 原有职责 | 原型阶段直接交付 |
|---|---|---|
| A 周子涵 | 两个传统策略、进度管控 | 两个传统基线的 manifest、参数说明、结果字段；维护原型里程碑 |
| B 陈湛霖 | 两个 ML 策略、2015–当前数据 | 两个 ML 基线 manifest、模型依赖、数据覆盖清单和示例结果 |
| C 李泽同 | 后端、LEAN 与云端部署、任务分派 | FastAPI 合同、Worker API、Smoke/Full job 状态、结果解析、System 页数据 |
| D 刘竞泽 | Agent 架构、DSL、代码优化 | 固化编排事件结构、DSL Builder、四级验证器、Compiler/Repair 合同 |

### 最先需要四人统一的接口文件

```text
shared/contracts/project_configuration.schema.json
shared/contracts/strategy_manifest.schema.json
shared/contracts/alphaforge_dsl_v1.schema.json
shared/contracts/dsl_validation_result.schema.json
shared/contracts/candidate_lineage.schema.json
shared/contracts/job_status.schema.json
shared/contracts/backtest_result_normalized.schema.json
shared/contracts/agent_event.schema.json
```

任何成员在这些结构未确定前，不应各自创建同名但字段不同的 JSON。

---

## 12. 本版需要团队进一步确认的问题

以下内容暂按推荐默认值设计，下一版可以修改：

1. DSL v1 具体支持哪些 feature、model、allocation 和 risk 模块；
2. QC Code Agent 是否直接收敛为确定性 Compiler，还是保留受控 LLM 代码槽位；
3. Smoke Test 的固定区间、超时和成功条件；
4. 三个候选是否串行运行，还是 Worker 支持有限并发；
5. ML 模型在 LEAN 任务内滚动训练，还是加载预训练产物；
6. Repair Agent 可修错误白名单和最大尝试次数是否固定为 2；
7. Candidate Selector 的硬门槛和综合评分公式；
8. 鲁棒性验证使用时间切分、市场阶段还是参数扰动；
9. 用户策略输入是否保留 QC Python 上传，还是 MVP 只允许内置模板/DSL；
10. 报告导出只做 JSON/HTML，还是增加 PDF。

---

## 13. 推荐的首版演示路径

课堂或 showcase 演示时，建议固定使用一个预置 Demo Project：

1. 打开 `AlphaForge Demo`；
2. 展示 30 股白名单中的示例子集、回测期间和风险约束；
3. 点击 Preflight，证明 LEAN Worker 和数据就绪；
4. 展示用户策略与四基线的真实结果；
5. 启动或回放一次 Agent 优化；
6. 展示 Traditional、ML、Hybrid 三个结构化候选及其 DSL 状态；
7. 打开 Hybrid 候选，展示 DSL → 四级验证 → QC Code → Static/Risk Check → Smoke → Full Backtest；
8. 在 Comparison Report 中解释收益、风险和鲁棒性；
9. 输出推荐，或诚实显示 `No Robust Improvement Found`。

为了避免现场等待，系统可以保留已完成结果，但必须能证明这些结果来自真实 LEAN 任务，并展示代码哈希、环境版本和日志。

---

## 14. MVP 完成定义

只有同时满足以下条件，才能称为真正的软件原型：

- 用户能通过前端创建并配置项目；
- 前端通过 FastAPI 提交任务，而不是手动复制文件；
- 至少一个真实策略能由前端触发本地 LEAN 回测；
- 后端能返回标准化指标和任务状态；
- 多智能体能输出三个通过四级校验的 AlphaForge DSL 候选；
- Designer 自然语言输出不会绕过 DSL 直接进入 LEAN；
- 至少一个候选能从 DSL 生成 LEAN 代码并完成 Smoke 与 Full Backtest；
- Repair Agent 的修改不改变 DSL hash，且不会超过最大修复次数；
- 前端能比较用户策略、基线和候选；
- 所有显示的实验数值都能追溯到真实任务；
- 每个结果都可追踪 `DSL hash → code hash → run id → result hash`；
- 风险约束能够否决不合法候选；
- 系统在没有稳健改善时不会强行推荐。
