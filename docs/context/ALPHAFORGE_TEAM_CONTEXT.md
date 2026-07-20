# AlphaForge 最新团队方案与 AI 上下文 v1.1

> **Project Title:** AlphaForge: A Risk-Aware Multi-Agent Platform for Automated Trading Strategy Optimization  
> **中文定位：** 面向学习、研究与决策支持的风险感知多智能体自动交易策略优化平台  
> **更新时间：** 2026-07-18  
> **适用对象：** AlphaForge 四人小组、指导老师、代码辅助 LLM、多智能体开发 Agent  
> **文档状态：** 当前团队主上下文；已按《SWS3022: AI Financial Innovation Challenge 2026》调整  
> **建议仓库位置：** `docs/context/ALPHAFORGE_TEAM_CONTEXT.md`

---

## 0. 这份文档怎么用

这份文件用于解决五个问题：

1. 大家现在到底在做什么；
2. 四个人的代码最后怎样接起来；
3. 每一阶段做到什么程度才算完成；
4. 新的 AI/LLM 加入工作时，应遵守哪些已确定的约束；
5. 如何满足最新课程评分、研究、教育、伦理和 Showcase 要求。

团队成员开始一个任务前，应先阅读：

- 第 2 节：最新端到端流程；
- 第 5 节：系统总架构；
- 第 7 节：仓库结构；
- 第 8 节：当前四人分工；
- 第 9 节：阶段化 To-Do List；
- 第 15 节：给 AI 的工作规则；
- 第 18–22 节：研究、教育价值、加分项和 Showcase 要求。

状态标记：

- `FROZEN`：已确认，不能由个人或 LLM 静默修改；
- `WORKING`：当前采用的工作方案，可经团队讨论调整；
- `OPEN`：尚未冻结，需要形成明确决定；
- `STRETCH`：时间充足再做，不阻塞 MVP。

---

## 1. 项目目标与评分导向

### 1.1 一句话说明

> AlphaForge 是一个面向量化学习、策略研究和风险决策支持的平台。系统先在统一的 QuantConnect/LEAN 环境中回测用户初始策略与四个基线策略，再由风险感知多智能体分析结果，分别生成纯传统、纯 ML、传统+ML 混合三类结构化候选策略；Code Generation Agent 将候选策略转换为 LEAN-compatible Python 代码，最终交给本地 LEAN 进行真实回测、比较、解释和稳健性验证。

### 1.2 项目真正要证明什么

AlphaForge 不是要证明“LLM 会写交易代码”，而是要证明：

> 多个具有不同职责的 Agent，能否基于真实回测证据，在风险、收益、成本和过拟合之间进行可解释的策略优化，并产出能够被 LEAN 实际执行、被用户理解和复现的策略。

### 1.3 最新课程评分对应（FROZEN）

| 评分项 | 权重 | AlphaForge 必须提供的证据 |
|---|---:|---|
| Problem Significance | 10% | 明确目标用户、真实策略开发痛点、使用场景和实际价值 |
| Literature Review | 15% | 至少 8 篇论文；5 篇近五年；2 篇权威出版社；1 篇综述；研究空白矩阵 |
| Innovation & Originality | 20% | 三路线候选、风险否决、Spec-to-Code-to-LEAN 闭环，并用消融实验证明价值 |
| AI/ML Methodology | 15% | 2 个 ML 基线、Multi-Agent + LLM、确定性 Validator、训练与防泄漏说明 |
| Technical Implementation | 15% | FastAPI、Streamlit、LEAN Worker、代码生成、结果解析、测试与可复现环境 |
| Frontend & User Experience | 10% | 清晰用户旅程、Learn & Explain Mode、进度与错误提示、小规模用户测试 |
| Experimental Evaluation | 10% | 统一回测、样本外、鲁棒性、消融、代码生成成功率和失败案例 |
| Presentation & Demonstration | 5% | 15 页内 Proposal、持续运行 Demo、Poster、QR、视频和项目主页 |

因此项目优先级调整为：

```text
真实问题 + 文献与研究空白
> LEAN 真实可复现闭环
> 四基线与三候选的可靠实验
> 可验证的多智能体创新
> 用户能够理解和操作的 Web 产品
> Showcase 与加分交付
```

### 1.4 真实问题、目标用户与实际用途

AlphaForge 解决的不是“缺少另一个股票预测模型”，而是以下真实问题：

- 策略研究者需要人工反复修改信号、参数和风险规则，实验成本高；
- 不同策略常使用不同区间、费用或成交规则，结果缺乏公平性；
- 只追求收益容易造成过拟合、过度换手和大幅回撤；
- LLM 可以生成代码，但生成结果可能无法执行、改变原策略含义或使用未来信息；
- 初学者能看到 Sharpe、Drawdown 等结果，却不理解策略为什么变化、风险来自哪里。

主要目标用户：

1. 学习算法交易和金融 AI 的学生；
2. 需要快速验证想法的初级量化研究者；
3. 希望在统一标准下比较策略的课程和研究团队。

实际用途：

- 把一个初始策略系统化地转化为多个可比较候选；
- 自动完成受控代码生成、LEAN 兼容检查和回测；
- 解释每次修改带来的收益—风险 trade-off；
- 保存完整实验、版本与审计轨迹，支持复现和教学；
- 帮助用户识别“高收益但脆弱”的策略，而不是提供直接投资建议。

### 1.5 教育价值与产品价值

AlphaForge 同时具有两种产品模式：

| 模式 | 目标 | 核心体验 |
|---|---|---|
| Research Mode | 策略开发与比较 | 完整参数、基线、Agent 优化、LEAN 结果、导出和复现 |
| Learn & Explain Mode | 金融 AI 和风险教育 | 指标解释、修改前后对照、风险原因、What-if 实验和引导式提示 |

教育模式不改变底层优化架构，只在相同结果之上增加解释层，因此不会显著扩大核心开发风险。

---

## 2. 最新端到端业务流程（FROZEN）

### 2.1 主流程

```text
用户设置并回测初始策略 S_user
        ↓
同一环境运行四个基线策略 B1–B4
        ↓
标准化用户策略、四基线与 Benchmark 的结果
        ↓
多智能体读取策略描述和回测证据
        ↓
生成三种候选 Strategy Spec
├── C-T：纯传统策略候选
├── C-ML：纯 ML 策略候选
└── C-H：传统 + ML 混合策略候选
        ↓
Schema + 语义 + 风险约束校验
        ↓
Code Generation Agent 生成三份 LEAN-compatible main.py
        ↓
静态检查 → LEAN 编译/Smoke Test → Repair Agent（有限次数）
        ↓
本地 LEAN 对三个候选进行完整回测
        ↓
结果标准化、风险检查和鲁棒性验证
        ↓
比较 S_user、B1–B4、C-T、C-ML、C-H 与 Benchmark
        ↓
选出最终策略，或输出“未发现稳健改进”
```

### 2.2 “用户回测”的含义

MVP 中，用户不是任意上传一段无法审计的 Python 代码。用户通过 Web：

- 选择 10–30 只白名单股票；
- 设置资金、日期和风险偏好；
- 选择一个支持的初始策略模板；
- 在允许范围内设置参数；
- 提交回测。

系统将这些输入保存为 `User Strategy Spec`，再生成或选择对应 QC/LEAN 代码运行。

`STRETCH`：未来可支持导入受限制的 QuantConnect Python 策略，但必须先做静态检查，并解决“任意代码如何反向理解为 Strategy Spec”的问题。该功能不阻塞课程项目。

### 2.3 为什么一定生成三类候选

| 候选 | 信号来源 | 研究意义 |
|---|---|---|
| C-T：Pure Traditional | 技术指标、统计规则、风险过滤 | 解释性强，提供低复杂度方案 |
| C-ML：Pure ML | 模型预测分数或概率 | 检验 ML 是否真正提供增量信息 |
| C-H：Hybrid | 传统信号 + ML 信号 | 研究二者互补是否能提高风险调整后表现 |

三个候选都必须经过相同的 LEAN 回测。不能由 Agent 在回测前凭文字判断哪个最好。

### 2.4 面向用户的解释闭环

主流程保持不变，但每次优化结果还应生成一组可解释内容：

```text
策略原来有什么问题
→ Agent 修改了哪些 Strategy Spec 字段
→ 为什么预计有效
→ LEAN 结果是否支持这个假设
→ 收益提高是否伴随更高回撤、波动或费用
→ 候选为什么被接受或拒绝
→ 用户可以进一步尝试什么 What-if 情景
```

解释必须引用真实指标和 Spec diff，不允许由 LLM 编造没有回测证据的原因。

---

## 3. 策略与实验对象

### 3.1 用户初始策略

标识：`S_user`

作用：

- 是本次优化的主要父策略；
- 与四个基线形成优化前对照；
- 多智能体结合它的策略结构和回测弱点提出改进。

### 3.2 四个基线策略（FROZEN：2 Traditional + 2 ML）

| ID | 类型 | 当前建议 | 输出 |
|---|---|---|---|
| B1 | Traditional | Momentum / Trend Ranking | QC `main.py` + Strategy Spec + 结果 |
| B2 | Traditional | Mean Reversion Ranking | QC `main.py` + Strategy Spec + 结果 |
| B3 | ML | Gradient Boosting 预测未来 21 日相对 SPY Alpha | QC `main.py` + 模型说明 + 结果 |
| B4 | ML | 第二种 ML 排名/方向预测模型 | QC `main.py` + 模型说明 + 结果 |

`OPEN-01`：B4 的最终算法需要由 ML 负责人在第一阶段冻结。建议优先选择能在 LEAN 环境稳定运行、与 B3 有明显差异的模型，例如 Random Forest 分类/回归；LSTM 只有在依赖、训练时间和部署均验证可控后再采用。

四个基线必须是真正不同的策略逻辑，不能只是同一模型换参数。

### 3.3 Benchmark

至少保留：

1. `SPY Buy & Hold`；
2. `Selected Universe Equal Weight`。

### 3.4 股票白名单（FROZEN）

标准实验使用 `whitelist_v1.0`：

```text
MSFT, AAPL, NVDA, GOOGL, AMZN, META, AVGO, ASML, AMD, ORCL,
JPM, BRK.B, V, LLY, JNJ, ABBV, TMO, WMT, COST, PG,
KO, MCD, CAT, HON, UNP, ETN, XOM, LIN, NEE, PLD
```

Ticker 映射：

- QuantConnect/LEAN：`BRK.B`；
- Yahoo Finance：`BRK-B`。

### 3.5 数据区间

第一阶段准备 2015 年至当前可用日期的数据。正式实验需要再划分：

- Training；
- Validation；
- 最终 Test。

`OPEN-02`：最终切分日期在数据完整性检查后冻结。Test 一旦保留，不能提供给优化 Agent，也不能用于选择候选。

---

## 4. 统一回测协议

所有策略只有在以下条件一致时才可直接比较：

| 项目 | 统一要求 |
|---|---|
| Engine | 固定版本的本地 QuantConnect LEAN |
| Language | LEAN-compatible QuantConnect Python |
| Universe | 同一用户股票池；标准实验为 30 只白名单 |
| Period | 同一起止日期和数据版本 |
| Resolution | Daily |
| Initial Cash | 默认 100,000 USD |
| Direction | Long-only |
| Leverage | No leverage |
| Cash | Allowed |
| Rebalance | 标准实验 Monthly |
| Holdings | 标准实验 Dynamic Top 3 |
| Position Cap | 35% |
| Benchmark | SPY + Universe Equal Weight |
| Normalization | Adjusted，具体映射写入配置 |
| Fee/Slippage | 固定模型并保存版本 |
| Time Zone | 固定并记录 |
| Seed | ML 策略固定随机种子 |

### 4.1 防止未来数据

- 决策时只能使用当时可见数据；
- ML 标签不得进入特征窗口；
- 时间序列不得随机打乱；
- Scaler、特征选择与模型都只在历史训练窗口拟合；
- 推荐 walk-forward/rolling training；
- Test 不进入 Agent 输入；
- 同日收盘信号不能假设以同一收盘价成交。

### 4.2 最低指标

- Total Return / CAGR；
- Sharpe Ratio；
- Sortino Ratio；
- Maximum Drawdown；
- Annualised Volatility；
- Alpha / Beta；
- Turnover；
- Total Fees；
- Win Rate / Total Orders；
- Equity Curve / Drawdown Curve。

除金融指标外，项目评估还应记录：

- Code Generation 编译成功率；
- 首次 Smoke Test 通过率；
- 平均 Repair 次数；
- 每次完整优化的运行时间；
- Agent 产生的非法 Spec 比例；
- 风险 Agent 拒绝候选的原因分布；
- 用户任务完成率和完成时间；
- Learn Mode 使用前后的风险知识小测变化；
- 用户满意度或简化版 SUS 可用性评分。

### 4.3 接受候选的原则

候选只有同时满足以下条件才可接受：

```text
LEAN 代码与 Strategy Spec 语义一致
且
在 Validation 上表现有合理改善
且
风险未出现不可接受恶化
且
不依赖极端参数或单一股票
且
通过至少三类鲁棒性测试
```

如果三个候选都不稳健，正确输出是：

```text
No robust improvement found under the current constraints.
```

---

## 5. 项目总体架构

### 5.1 六层架构

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Presentation Layer                                      │
│ Streamlit：策略配置、结果对比、Learn & Explain、最终报告     │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / JSON
┌──────────────────────────▼──────────────────────────────────┐
│ 2. Application Layer                                       │
│ FastAPI：请求校验、任务编排、版本管理、结果查询              │
└───────────────┬──────────────────────┬──────────────────────┘
                │                      │
┌───────────────▼──────────────┐  ┌────▼─────────────────────┐
│ 3. Multi-Agent Layer         │  │ 4. Strategy Layer        │
│ Analysis / Design / Risk     │  │ Strategy Spec / Schema   │
│ Robustness / Decision        │  │ Validator / Versioning   │
│ Code Generation / Repair     │  │ Three Candidate Builder  │
└───────────────┬──────────────┘  └────┬─────────────────────┘
                └──────────────┬────────┘
                               │ validated spec / code
┌──────────────────────────────▼──────────────────────────────┐
│ 5. Backtest Execution Layer                                │
│ Code Validator → Local LEAN Worker → Result Parser          │
│ Optional QuantConnect Cloud Provider                        │
└──────────────────────────────┬──────────────────────────────┘
                               │ standardized results
┌──────────────────────────────▼──────────────────────────────┐
│ 6. Evaluation & Storage Layer                              │
│ Metrics / Risk / Robustness / Explainability / UX / Audit   │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 模块边界

- Streamlit 不直接运行 LEAN，也不计算最终指标；
- FastAPI 只负责任务和服务编排，不实现策略公式；
- Agent 不能绕过 Strategy Spec 和 Validator；
- Code Generation Agent 不能擅自修改策略语义；
- Repair Agent 只能修复编译/运行实现，不能改变策略逻辑；
- LEAN 是最终回测执行者和原始结果来源；
- 统一 Result Parser 将不同策略结果转成相同 Schema；
- Evaluation Layer 基于真实结果作选择，不接受 Agent 虚构指标；
- Explainability Layer 只能基于 Spec diff、LEAN 指标和风险检查生成说明；
- Learn Mode 与 Research Mode 共用同一结果，不能为了教学页面重新计算一套指标；
- 数据目录、LEAN 版本、模型、Prompt 和 Strategy Spec 都必须版本化或留有 manifest。

### 5.3 回测 Provider

```text
BacktestProvider
├── LocalLeanProvider          # MVP 主路径
└── QuantConnectCloudProvider  # STRETCH / 交叉验证 / 备用
```

本项目当前优先本地 LEAN，降低云端 API 成本和限额依赖。两种 Provider 应尽量接收同一份 `main.py`，但结果是否一致必须通过实际实验验证，不能只根据代码形式兼容就假设完全一致。

---

## 6. 多智能体优化架构

### 6.1 Agent 角色

| Agent | 输入 | 输出 | 限制 |
|---|---|---|---|
| Baseline Analyst | S_user、B1–B4、Benchmark 结果 | 主要优势/问题和市场阶段分析 | 不修改策略 |
| Traditional Strategy Agent | 分析结果、父 Spec、传统 Operator | C-T Strategy Spec 草案 | 不使用 ML 信号 |
| ML Strategy Agent | 数据/模型报告、父 Spec、ML Operator | C-ML Strategy Spec 草案 | 不偷偷加入传统信号 |
| Hybrid Strategy Agent | 传统与 ML 信号报告 | C-H Strategy Spec 草案 | 明确融合方式与权重 |
| Risk Reviewer | 三类候选与约束 | 风险警告、修订或拒绝 | 有否决权 |
| Spec Validator | 完整 Spec | valid/invalid + 错误 | 确定性程序优先 |
| Code Generation Agent | 已验证 Spec + LEAN 模板/API 白名单 | `main.py` + 假设 | 不改 Spec |
| Repair Agent | Spec、代码、真实错误日志 | 修复后的代码 | 最多 2–3 次，不改语义 |
| Robustness Agent | LEAN 标准化结果 | 稳健性测试计划和判断 | 不读取保留 Test 来调参 |
| Decision Agent | 全部真实结果 | accept/reject/continue + 理由 | 受风险否决和迭代预算约束 |
| Explainability Service/Agent | Spec diff、LEAN 指标、风险结果 | 面向用户的修改卡片、指标解释与证据链接 | 不参与候选选择，不得编造因果 |

### 6.2 推荐执行顺序

```text
Baseline Analyst
→ Traditional / ML / Hybrid Agents 并行产出三类候选
→ Risk Reviewer 预检查
→ 确定性 Schema/语义校验
→ Code Generation Agent
→ 静态代码检查
→ LEAN Smoke Test
→ Repair Agent（仅失败时）
→ LEAN Full Backtest
→ Risk + Robustness + Decision
→ Explainability Service 生成证据化解释
```

### 6.3 迭代限制

- MVP 最多 2 轮优化；
- 每轮保持三种路线各 1 个主要候选；
- Repair 最多 2–3 次；
- 每轮只改变有限字段；
- 保存所有候选、失败原因和 Agent 理由；
- 不允许因为 Test 差而重新优化；
- 不要求一定选出“成功策略”。

### 6.4 Strategy Spec 的地位

```text
Strategy Spec = 策略含义的 Source of Truth
generated main.py = 可重新生成的执行产物
LEAN result = 评价产物
```

每个候选至少保存：

```text
strategy_spec.json
parent_strategy_id
candidate_type                  # traditional / ml / hybrid
changes_from_parent.json
agent_reasoning_summary.json
generated_main.py
generator_model_and_prompt.json
static_validation.json
compile_and_smoke_result.json
lean_environment.json
backtest_result_raw.json
backtest_result_normalized.json
risk_result.json
robustness_result.json
decision_result.json
```

---

## 7. 推荐仓库与文件夹结构

### 7.1 Monorepo 结构

```text
alphaforge/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docker-compose.yml                  # 可选：API/Web/LEAN Worker
│
├── docs/
│   ├── context/
│   │   └── ALPHAFORGE_TEAM_CONTEXT.md  # 本文档
│   ├── architecture/
│   │   ├── SYSTEM_ARCHITECTURE.md
│   │   └── AGENT_ARCHITECTURE.md
│   ├── strategies/
│   │   ├── BASELINE_RESEARCH.md
│   │   ├── TRADITIONAL_BASELINES.md
│   │   └── ML_BASELINES.md
│   ├── research/
│   │   ├── LITERATURE_REVIEW.md
│   │   ├── PAPER_MATRIX.xlsx
│   │   ├── REFERENCES.bib
│   │   └── RELATED_SYSTEMS.md
│   ├── data/
│   │   ├── DATA_SOURCES.md
│   │   ├── CLEANING_PIPELINE.md
│   │   └── LICENSE_AND_ETHICS.md
│   ├── ux/
│   │   ├── USER_PERSONAS.md
│   │   ├── USER_STUDY_PLAN.md
│   │   └── USER_STUDY_RESULTS.md
│   ├── governance/
│   │   ├── AI_USE_DISCLOSURE.md
│   │   └── THIRD_PARTY_NOTICES.md
│   ├── lean/
│   │   ├── LOCAL_LEAN_SETUP.md
│   │   ├── DATA_REQUIREMENTS.md
│   │   └── QC_COMPATIBILITY_REPORT.md
│   ├── api/
│   ├── experiments/
│   └── decisions/                      # ADR：重要冻结决策
│
├── apps/
│   ├── api/
│   │   ├── main.py                     # FastAPI 入口
│   │   └── routes/
│   │       ├── strategies.py
│   │       ├── backtests.py
│   │       ├── optimisations.py
│   │       └── reports.py
│   └── web/
│       ├── Home.py                     # Streamlit 入口
│       ├── pages/
│       └── components/
│
├── src/alphaforge/
│   ├── config.py
│   ├── schemas/                        # 跨模块唯一接口定义
│   │   ├── strategy_spec.py
│   │   ├── backtest.py
│   │   ├── optimisation.py
│   │   └── agent_outputs.py
│   │
│   ├── agents/
│   │   ├── baseline_analyst.py
│   │   ├── traditional_designer.py
│   │   ├── ml_designer.py
│   │   ├── hybrid_designer.py
│   │   ├── risk_reviewer.py
│   │   ├── robustness_agent.py
│   │   ├── decision_agent.py
│   │   ├── code_generator.py
│   │   ├── repair_agent.py
│   │   ├── orchestrator.py
│   │   ├── prompts/                    # Prompt 必须版本化
│   │   └── providers/                  # LLM API + mock
│   │
│   ├── strategy_spec/
│   │   ├── schema.json
│   │   ├── validator.py
│   │   ├── semantic_validator.py
│   │   ├── patch.py
│   │   └── versioning.py
│   │
│   ├── codegen/
│   │   ├── generator.py
│   │   ├── code_validator.py
│   │   ├── api_allowlist.py
│   │   └── templates/
│   │       ├── base_algorithm.py.j2
│   │       ├── traditional.py.j2
│   │       ├── ml.py.j2
│   │       └── hybrid.py.j2
│   │
│   ├── backtest/
│   │   ├── provider.py                 # BacktestProvider 接口
│   │   ├── local_lean.py
│   │   ├── quantconnect_cloud.py       # STRETCH
│   │   ├── job_manager.py
│   │   ├── result_parser.py
│   │   └── environment_manifest.py
│   │
│   ├── evaluation/
│   │   ├── metrics.py
│   │   ├── comparisons.py
│   │   ├── risk_checks.py
│   │   ├── robustness.py
│   │   ├── explainability.py
│   │   ├── learning_evaluation.py
│   │   └── candidate_selector.py
│   │
│   ├── data/
│   │   ├── catalog.py
│   │   ├── validation.py
│   │   ├── ticker_map.py
│   │   └── metadata.py
│   │
│   ├── services/
│   │   ├── strategy_service.py
│   │   ├── backtest_service.py
│   │   ├── optimisation_service.py
│   │   └── report_service.py
│   │
│   └── storage/
│       ├── repository.py
│       ├── local_repository.py
│       └── models.py
│
├── qc_strategies/
│   ├── user_templates/                 # MVP 用户初始策略模板
│   ├── baselines/
│   │   ├── traditional/
│   │   │   ├── momentum/main.py
│   │   │   └── mean_reversion/main.py
│   │   └── ml/
│   │       ├── ml_baseline_1/main.py
│   │       └── ml_baseline_2/main.py
│   ├── smoke/
│   │   └── sma_smoke_test/main.py       # 最小 LEAN 验证策略
│   └── generated/                       # 运行时生成，通常不直接提交全部产物
│       ├── traditional_candidate/
│       ├── ml_candidate/
│       └── hybrid_candidate/
│
├── specs/
│   ├── examples/
│   ├── users/
│   ├── baselines/
│   └── candidates/
│       ├── traditional/
│       ├── ml/
│       └── hybrid/
│
├── configs/
│   ├── whitelist_v1.0.yaml
│   ├── backtest_standard_v1.yaml
│   ├── data_split_v1.yaml
│   ├── lean_environment_v1.yaml
│   └── robustness_v1.yaml
│
├── infra/
│   └── lean/
│       ├── README.md                    # 本地 LEAN 安装与运行
│       ├── Dockerfile                   # 若采用容器 Worker
│       ├── config.example.json
│       ├── run_job.py
│       └── parse_result.py
│
├── data_catalog/                        # 只提交元数据，不提交大型行情
│   ├── README.md
│   ├── symbols.csv
│   ├── availability_2015_present.csv
│   ├── quality_report.json
│   └── checksums.json
│
├── experiments/
│   ├── manifests/                       # commit/config/data/seed/run_id
│   ├── baselines/
│   ├── candidates/
│   ├── ablations/
│   ├── robustness/
│   └── reports/
│
├── artifacts/                           # 默认 gitignore，可重新生成
│   ├── lean_jobs/
│   ├── lean_results/
│   ├── generated_code/
│   ├── models/
│   └── charts/
│
├── showcase/
│   ├── poster/
│   ├── qr/
│   ├── demo_video/
│   ├── demo_script/
│   └── fallback_results/
│
├── scripts/
│   ├── validate_qc_strategy.py
│   ├── run_local_lean.py
│   ├── run_four_baselines.py
│   ├── run_three_candidates.py
│   ├── normalize_results.py
│   └── export_report.py
│
└── tests/
    ├── unit/
    ├── integration/
    ├── regression/
    └── fixtures/
```

### 7.2 LEAN 本体和数据不要直接塞进 Git

仓库中的 `infra/lean/` 只保存：

- 安装说明；
- Dockerfile/启动脚本；
- 配置模板；
- Job 封装；
- 结果解析器。

LEAN 源码、Docker image、本地行情和大体积结果由环境变量定位，例如：

```text
LEAN_ROOT=
LEAN_DATA_DIR=
LEAN_RESULTS_DIR=
```

原因：

- LEAN 仓库与数据体积较大；
- 数据可能有许可限制；
- 每个人本地路径不同；
- Git 应保存“如何复现环境”，而不是复制所有环境文件。

### 7.3 目录责任

| 目录 | 当前第一负责人 |
|---|---|
| `docs/strategies/`, `qc_strategies/baselines/traditional/` | Member A |
| `qc_strategies/baselines/ml/`, `data_catalog/` | Member B |
| `infra/lean/`, `src/alphaforge/backtest/`, LEAN 兼容报告 | Member C |
| `src/alphaforge/agents/`, `strategy_spec/`, `codegen/` 架构 | Member D |
| `src/alphaforge/schemas/` | 全员评审，相关负责人提交 |
| `docs/research/` | 四人各负责论文，最终由一人统一格式与论证 |
| `docs/data/` | Member B+C |
| `docs/ux/`, `showcase/` | 后续 Web 主负责人组织，全员参与 |
| `docs/governance/` | 全员提供记录，Member D 汇总 AI 使用 |
| `apps/`, 最终集成与展示 | 后续阶段再确认主负责人 |

### 7.4 允许的依赖方向

```text
Streamlit → FastAPI → Services
Services → Agents / Strategy Spec / Backtest Provider / Evaluation
Agents → Schemas + 标准化结果 + Strategy Spec
Codegen → 已验证 Strategy Spec + Templates
LocalLeanProvider → QC main.py + LEAN 环境
ResultParser → LEAN raw results → Standard BacktestResult
```

禁止：

- UI 直接执行 LEAN；
- Agent 直接写入本地 LEAN 数据目录；
- Code Generation Agent 修改 Strategy Spec；
- ML 策略读取 Test 标签；
- Notebook 成为正式服务依赖；
- 四个基线使用四套不同指标计算方式。

---

## 8. 当前第一阶段四人分工（FROZEN）

成员姓名确定后，将 A/B/C/D 替换为实际姓名。

### Member A：策略调研与两个传统策略 QC 代码

负责：

1. 调研适合本项目展示的传统策略；
2. 冻结 B1、B2 的公式、参数、买卖/调仓逻辑；
3. 实现两份 QuantConnect Python `main.py`；
4. 在 QuantConnect Cloud 或已有环境中先完成回测；
5. 给出策略解释、风险点和所需数据；
6. 为每个策略写一个初步 Strategy Spec。

建议策略：

- B1 Momentum / Trend Ranking；
- B2 Mean Reversion Ranking。

第一阶段交付物：

```text
docs/strategies/BASELINE_RESEARCH.md
docs/strategies/TRADITIONAL_BASELINES.md
qc_strategies/baselines/traditional/momentum/main.py
qc_strategies/baselines/traditional/mean_reversion/main.py
specs/baselines/traditional_1.json
specs/baselines/traditional_2.json
```

验收：

- 两个策略在 QC 环境可运行；
- 明确何时计算信号、何时买入、何时卖出；
- 不使用未来数据；
- 使用 30 只白名单；
- 输出结果截图或 JSON；
- 代码中所有关键参数都有说明。

### Member B：两个 ML 策略 QC 代码与 2015–当前数据准备

负责：

1. 冻结 B3、B4 的模型选择；
2. 设计特征、标签、训练窗口和预测频率；
3. 实现两个 QuantConnect Python ML 策略；
4. 准备/核对 30 只股票从 2015 年到当前的数据；
5. 生成数据可用性、缺失、上市日期和 Ticker 映射报告；
6. 明确 QC 内置历史数据与本地 LEAN 所需数据的关系；
7. 记录 Python/模型依赖和随机种子。

工作建议：

- B3：Gradient Boosting Regression，预测未来 21 日相对 SPY Alpha；
- B4：优先验证 Random Forest 分类/回归；LSTM 作为有条件方案。

第一阶段交付物：

```text
docs/strategies/ML_BASELINES.md
qc_strategies/baselines/ml/ml_baseline_1/main.py
qc_strategies/baselines/ml/ml_baseline_2/main.py
specs/baselines/ml_1.json
specs/baselines/ml_2.json
data_catalog/availability_2015_present.csv
data_catalog/quality_report.json
data_catalog/symbols.csv
```

验收：

- 两个 ML 策略在 QC 环境可执行；
- 训练和预测时间顺序正确；
- 不随机打乱金融时间序列；
- 每个预测时点只使用过去数据；
- 2015–当前的数据覆盖情况可查；
- 明确哪些数据可以合法复制/下载到本地 LEAN；
- B3 与 B4 在模型或任务定义上有明显差异。

### Member C：本地 LEAN 部署、QC 代码兼容性与数据需求验证

负责：

1. 在本地或 Docker 中部署固定版本 LEAN；
2. 先用最简单 SMA 策略跑通 Smoke Test；
3. 接收 A/B 的四份 QC `main.py`，逐份测试本地兼容性；
4. 记录编译、运行、依赖和 API 差异；
5. 确定 LEAN 对 2015–当前 30 只股票所需的完整数据类型；
6. 明确 equities、factor files、map files 等数据要求；
7. 解析 LEAN 原始结果，至少拿到 Sharpe 和 Maximum Drawdown；
8. 输出可重复的安装和运行命令。

第一阶段交付物：

```text
infra/lean/README.md
infra/lean/config.example.json
infra/lean/run_job.py
infra/lean/parse_result.py
qc_strategies/smoke/sma_smoke_test/main.py
docs/lean/LOCAL_LEAN_SETUP.md
docs/lean/DATA_REQUIREMENTS.md
docs/lean/QC_COMPATIBILITY_REPORT.md
```

验收：

- 新环境按说明能启动 LEAN；
- SMA Smoke Test 成功；
- 至少一份 A/B 提供的真实策略在本地跑通；
- 四份策略各自有 pass/fail 和错误原因；
- 能从结果中自动解析 Sharpe、Max Drawdown；
- 明确本地数据缺口及解决方案；
- 固定并记录 LEAN 版本。

### Member D：AI Agent 代码优化架构设计

负责：

1. 设计多智能体角色、输入输出和 Orchestrator；
2. 定义三种候选的 Strategy Spec 共同字段和专属字段；
3. 设计 `BaselineResult → Agent Analysis → 3 Candidate Specs` 流程；
4. 设计 `Strategy Spec → Code Generation Agent → main.py` 流程；
5. 设计静态检查、错误反馈与 Repair Agent；
6. 定义 Agent 输出的 Pydantic/JSON Schema；
7. 使用 mock 结果完成不依赖真实 LLM/LEAN 的流程原型；
8. 设计风险否决、最大迭代与审计日志。

第一阶段交付物：

```text
docs/architecture/AGENT_ARCHITECTURE.md
docs/architecture/SYSTEM_ARCHITECTURE.md
src/alphaforge/schemas/strategy_spec.py
src/alphaforge/schemas/agent_outputs.py
src/alphaforge/agents/orchestrator.py
src/alphaforge/agents/providers/mock.py
src/alphaforge/strategy_spec/validator.py
src/alphaforge/codegen/generator.py           # 初期可为接口或模板原型
tests/unit/test_strategy_spec.py
tests/integration/test_mock_optimisation.py
```

验收：

- 能用 mock 的 5 组回测结果生成 3 类候选 Spec；
- 3 类候选在 Schema 中可区分；
- 非法参数和越权修改能被拒绝；
- Code Agent 输入输出合同明确；
- Repair Agent 不允许改策略语义；
- 整个 mock 流程有明确状态与停止条件；
- 架构能接入 Member C 后续提供的真实 LEAN Result。

### 8.1 第一阶段依赖关系

```text
Member A ──两份传统 QC 代码──┐
                              ├──→ Member C 本地 LEAN 兼容测试
Member B ──两份 ML QC 代码────┘
Member B ──数据目录与质量报告──→ Member C 确认 LEAN 数据缺口
Member C ──标准结果样例────────→ Member D 定义 Agent 输入
Member A/B ─策略字段与参数─────→ Member D 定义 Strategy Spec
Member D ──Schema/结果合同─────→ 全员统一后续接口
```

### 8.2 第一阶段共同接口

四位成员在开始大量编码前，先共同提交三个最小样例：

1. `strategy_manifest.json`：说明策略 ID、类型、参数、代码入口和数据需求；
2. `lean_environment.json`：说明 Engine、数据、Python、Fee/Slippage 等环境；
3. `backtest_result_normalized.json`：说明 Agent 未来会读取的统一结果。

### 8.3 最新标准要求的共同研究任务

文献综述不是 Member A 一个人的策略调研附属任务，而是全组共同的 15 分交付：

| 成员 | 文献方向 | 最低任务 |
|---|---|---|
| A | 传统量化、组合优化和风险控制 | 2 篇精读并填写 Paper Matrix |
| B | ML 股票预测、排序和金融时间序列 | 2 篇精读并填写 Paper Matrix |
| C | 回测偏差、Walk-forward、复现和评估 | 2 篇精读并填写 Paper Matrix |
| D | Financial LLM、Multi-Agent、代码生成和安全 | 2 篇精读并填写 Paper Matrix |

全组最终必须满足：

- 至少 8 篇研究论文；
- 至少 5 篇为近五年论文；
- 至少 2 篇来自 IEEE、ACM、Springer、Elsevier、Nature 等权威出版机构；
- 至少 1 篇综述论文；
- 不是简单拼接摘要，而是比较当前方法、优势、局限、研究空白和 AlphaForge 创新机会。

同时新增：

- Member B+C 共同记录数据来源、采集、清洗和许可限制；
- 全员定义目标用户、真实痛点和资源 Required/Optional；
- Proposal 至少使用 2 篇论文，且总页数不超过 15 页；
- 所有 AI 生成代码必须有人类复核记录。

---

## 9. 阶段化 To-Do List

### Phase 1：并行技术验证与四基线准备（当前阶段）

#### 全员先冻结

- [ ] 建立仓库基础目录；
- [ ] 冻结 `whitelist_v1.0`；
- [ ] 冻结四个基线 ID 和名字；
- [ ] 冻结统一回测参数；
- [ ] 冻结 Strategy Manifest 和 Result Schema；
- [ ] 约定 Python/LEAN/依赖版本；
- [ ] 约定分支、PR 和合并规则。
- [ ] 每人完成 2 篇论文的 Literature Matrix；
- [ ] 选定至少 1 篇 survey 和 2 篇权威出版社论文；
- [ ] 写出目标用户、真实金融问题和现有工作流；
- [ ] 建立 Required/Optional 资源表；
- [ ] 建立数据来源、清洗、许可和 AI 使用披露文档骨架。

#### Member A

- [ ] 完成策略调研；
- [ ] 完成两个传统 QC 策略；
- [ ] 写清买入、卖出和调仓时点；
- [ ] 提供两份 Strategy Spec 草案；
- [ ] 提供 QC 初步结果。

#### Member B

- [ ] 冻结两个 ML 模型；
- [ ] 完成特征、标签和 walk-forward 方案；
- [ ] 完成两个 ML QC 策略；
- [ ] 准备 2015–当前数据 catalog；
- [ ] 输出数据质量与依赖报告。

#### Member C

- [ ] 部署固定版 Local LEAN；
- [ ] 跑通 SMA Smoke Test；
- [ ] 测试四份 QC 代码；
- [ ] 确认所需数据与缺口；
- [ ] 输出兼容性报告；
- [ ] 解析标准回测结果。

#### Member D

- [ ] 完成 Agent 总架构；
- [ ] 定义 3 类 Candidate Spec；
- [ ] 定义 Agent I/O Schema；
- [ ] 实现 mock optimisation；
- [ ] 定义 Codegen/Repair 合同；
- [ ] 准备 Strategy Spec Validator 原型。

**Phase 1 出口条件：**

- 四份 QC 策略代码已存在且有 QC 运行证据；
- Local LEAN 已跑通至少一个真实基线；
- 数据需求和 2015–当前覆盖情况明确；
- mock Agent 能产生传统/ML/混合三份合法 Spec；
- 全员使用同一 Strategy Manifest 与 Backtest Result Schema；
- 8 篇论文矩阵完成，Proposal 可直接使用其中至少 2 篇；
- 数据来源、许可、目标用户和实际价值已经有书面说明。

### Phase 2：四基线本地 LEAN 全部跑通

- [ ] Member C 将 A/B 四份策略全部移植/修复到本地 LEAN；
- [ ] A/B 对修复后的代码进行策略语义复核；
- [ ] 所有策略使用同一回测配置；
- [ ] 统一解析四策略与 Benchmark 结果；
- [ ] 建立回归测试，避免结果无意漂移；
- [ ] 保存 LEAN/data/code manifest；
- [ ] 输出第一版 Baseline Comparison。

**出口条件：** B1–B4 + 2 Benchmark 在固定环境中成功运行且结果可比较。

### Phase 3：Strategy Spec v1 与确定性代码生成

- [ ] 冻结 Strategy Spec v1；
- [ ] 覆盖两个传统、两个 ML 和混合信号所需字段；
- [ ] 实现 Schema + 语义验证；
- [ ] 把四个基线分别写成 Spec；
- [ ] 先使用确定性模板从 Spec 生成代码；
- [ ] 对生成代码进行格式化和静态检查；
- [ ] 对比手写与生成代码的策略语义和结果。

**出口条件：** 至少一个传统和一个 ML Spec 能自动生成可在 LEAN 运行的代码。

### Phase 4：Code Generation Agent 与自动修复

- [ ] 接入真实 Code Generation Agent；
- [ ] 限制 LEAN API 白名单；
- [ ] 固定 Prompt 和模型版本；
- [ ] 输出代码、假设和不支持项；
- [ ] 实现编译/运行错误回传；
- [ ] 实现 Repair Agent；
- [ ] 限制最大修复次数；
- [ ] 加入语义一致性检查。

**出口条件：** 3 类示例 Spec 均可经过 Agent 生成代码，并完成 Smoke Test；失败时有可解释状态。

### Phase 5：风险感知多智能体优化闭环

- [ ] 接入真实 S_user 和四基线结果；
- [ ] Baseline Analyst 输出结构化诊断；
- [ ] 三个 Designer 分别生成 C-T、C-ML、C-H；
- [ ] Risk Reviewer 预审；
- [ ] 三份候选分别生成代码并回测；
- [ ] 结果返回 Robustness/Decision Agent；
- [ ] 保存每轮修改和理由；
- [ ] 实现 accept/reject/continue；
- [ ] 限制为最多 2 轮。

**出口条件：** 从真实基线结果出发，自动生成并回测 3 类候选，最终选择或拒绝。

### Phase 6：鲁棒性与消融实验

- [ ] 时间顺序 Training/Validation/Test；
- [ ] Walk-forward；
- [ ] 参数扰动；
- [ ] 交易成本/滑点扰动；
- [ ] 股票池随机剔除或行业子池；
- [ ] Bull/Bear/Sideways 分段；
- [ ] 单 Agent vs Multi-Agent，或无 Risk Agent vs 有 Risk Agent；
- [ ] 单候选生成 vs 三路线候选；
- [ ] 自由代码生成 vs Strategy Spec 约束生成的成功率；
- [ ] Explainability 输出与真实 Spec diff/指标一致性抽查；
- [ ] Test 仅在策略完全锁定后运行一次；
- [ ] 记录失败候选。

**出口条件：** 能用实验说明多智能体和风险层是否提供真实价值，而不是只展示架构。

### Phase 7：FastAPI + Streamlit Web MVP

- [ ] Strategy Setup 页面；
- [ ] 用户初始策略回测；
- [ ] 四基线对比页面；
- [ ] 三类候选与 Agent 过程页面；
- [ ] LEAN 任务进度和错误页面；
- [ ] Robustness Lab；
- [ ] Final Report；
- [ ] Research Mode / Learn & Explain Mode 切换；
- [ ] 指标词典与风险提示；
- [ ] “修改了什么—为什么—结果是否支持”的解释卡片；
- [ ] What-if Lab：费用、最大回撤阈值、市场过滤等小范围情景；
- [ ] 轻量 Strategy Challenge：用户先选择候选，再揭示风险调整后结果（STRETCH）；
- [ ] 5–10 名目标用户的任务测试或简化 SUS；
- [ ] 导出 Strategy Spec、代码和结果；
- [ ] API 异步任务与缓存；
- [ ] Demo 备用结果快照；
- [ ] 公共可访问的 Streamlit/项目展示地址，或可解释的部署替代方案。

**出口条件：** 用户不用修改代码即可完成“初始策略 → 四基线 → 三候选 → LEAN 回测 → 最终报告”，并能理解至少一个修改理由、一个风险 trade-off 和一个拒绝原因。

### Phase 8：最终实验、答辩与交付

- [ ] 冻结代码 commit、LEAN 版本、数据版本、Prompt 版本；
- [ ] 运行最终标准实验；
- [ ] 生成同口径图表和表格；
- [ ] 检查所有数字可追溯到 run_id；
- [ ] README 和一键启动；
- [ ] Proposal 不超过 15 页，并覆盖老师要求的全部栏目；
- [ ] 最终材料逐项对应最新 10/15/20/15/15/10/10/5 评分结构；
- [ ] 完成 Literature Review、References 和引用检查；
- [ ] 完成 Poster：Problem / Innovation / AI Architecture / Results / QR；
- [ ] QR 链接 GitHub、Streamlit Application、Demo Video、Project Website；
- [ ] AI Use Disclosure 与 Third-party Notices；
- [ ] 数据来源、清洗和许可说明；
- [ ] 用户测试结果与前端改进记录；
- [ ] Docker/部署说明和可选开源 Release；
- [ ] 每位成员准备自己模块说明；
- [ ] 主 Demo、备用录像和离线结果；
- [ ] 展会应用连续运行和故障恢复测试；
- [ ] 清理 API key、绝对路径和不可复现文件。

**出口条件：** 新环境按文档可启动；所有结论有真实 LEAN 结果；访客可互动；Poster 和 QR 齐全；Demo 有网络失败备用方案；所有外部来源和 AI 使用已披露。

---

## 10. 第一阶段建议节奏

### 第一次同步会

- 冻结 B1–B4 名字；
- 统一 QC 代码格式和目录；
- Member C 提供最小本地 LEAN 提交格式；
- Member D 提供 Strategy Manifest/Result Schema 草案；
- 确认数据传递方式，避免把大型行情提交到 Git。

### 中期联调

- A 先尽早提交一个最简单传统策略给 C；
- B 先提交一个不依赖复杂库的 ML 最小版本给 C；
- C 不等待四个策略全完成，先验证一传统一 ML；
- D 使用 C 的真实结果样例替换 mock；
- A/B 检查 D 的 Spec 能否准确描述自己的策略。

### 阶段末集成

- C 对四个策略出兼容矩阵；
- A/B 修复策略语义问题；
- D 用四策略标准结果生成三候选 mock Spec；
- 全员确认下一阶段的唯一接口版本。

---

## 11. 跨模块数据合同

### 11.1 Strategy Manifest

```json
{
  "strategy_id": "baseline_b1_momentum_v1",
  "strategy_family": "traditional",
  "entry_file": "qc_strategies/baselines/traditional/momentum/main.py",
  "spec_file": "specs/baselines/traditional_1.json",
  "resolution": "daily",
  "symbols_source": "whitelist_v1.0",
  "parameters": {},
  "data_requirements": [],
  "python_dependencies": [],
  "random_seed": null
}
```

### 11.2 LEAN Environment Manifest

```json
{
  "provider": "local_lean",
  "lean_version": "fixed-tag-or-commit",
  "python_version": "fixed-version",
  "data_version": "catalog-version",
  "normalization_mode": "adjusted",
  "brokerage_model": "to-be-frozen",
  "fee_model": "to-be-frozen",
  "slippage_model": "to-be-frozen",
  "time_zone": "to-be-frozen"
}
```

### 11.3 Standard Backtest Result

```json
{
  "run_id": "uuid",
  "strategy_id": "baseline_b1_momentum_v1",
  "status": "completed",
  "engine": {},
  "period": {},
  "metrics": {
    "cagr": null,
    "sharpe_ratio": null,
    "sortino_ratio": null,
    "max_drawdown": null,
    "annual_volatility": null,
    "turnover": null,
    "total_fees": null
  },
  "artifacts": {},
  "warnings": [],
  "reproducibility": {}
}
```

### 11.4 Candidate Bundle

```json
{
  "optimization_id": "uuid",
  "parent_strategy_id": "user_strategy_v1",
  "candidate_type": "traditional | ml | hybrid",
  "strategy_spec": {},
  "changes_from_parent": [],
  "design_reason": [],
  "expected_tradeoffs": [],
  "risk_warnings": [],
  "code_generation_status": "pending",
  "backtest_status": "pending"
}
```

正式代码以 `src/alphaforge/schemas/` 中的 Pydantic 模型为唯一事实来源；本文 JSON 只是团队联调草案。

---

## 12. Git 与协作规则

### 12.1 建议分支

```text
feature/traditional-baselines
feature/ml-baselines-data
feature/local-lean
feature/agent-architecture
```

### 12.2 提交要求

每个 PR 至少说明：

- 修改内容；
- 策略/接口是否变化；
- 如何运行；
- 测试结果；
- 已知限制；
- 是否需要其他成员同步修改；
- 使用了哪些外部代码、论文或 AI 工具；
- 提交者如何验证并理解生成代码。

### 12.3 不提交的内容

- API key；
- QuantConnect 凭证；
- 大型 LEAN 数据；
- Docker image；
- 本地绝对路径；
- 可由脚本再生成的大型结果；
- 未明确许可的数据。

GitHub 可作为加分和展示证据，但公开仓库必须：

- 不包含受限市场数据和密钥；
- 有清晰 README、架构图、运行说明和许可证；
- 使用 Issues/PR/Decision Log 体现团队工程过程；
- 对 LEAN、第三方库、论文和生成内容做适当引用。

### 12.4 Definition of Done

任务只有同时满足以下条件才算完成：

- 代码可运行；
- 有运行或测试命令；
- 输入输出符合共同 Schema；
- 错误路径有说明；
- 关键决策写入文档；
- 与至少一个相邻模块完成联调；
- 没有把真实结果用手工数字替代。

---

## 13. 当前未决事项

| ID | 待确认事项 | 建议 | 负责人 | 截止 |
|---|---|---|---|---|
| OPEN-01 | 第二个 ML 基线 | 先验证 Random Forest；LSTM 为有条件备选 | B | Phase 1 前半 |
| OPEN-02 | Train/Validation/Test 日期 | 数据质量完成后按时间冻结 | A+B | Phase 1 末 |
| OPEN-03 | LEAN 固定版本 | 选定 Docker tag/commit 并写 manifest | C | Phase 1 前半 |
| OPEN-04 | 数据获得方式与许可 | 先列需求，再确定合法来源 | B+C | Phase 1 末 |
| OPEN-05 | Fee/Slippage/Brokerage | 统一配置，不沿用各策略私有默认 | A+C | Phase 1 末 |
| OPEN-06 | 用户初始策略模板范围 | MVP 提供有限模板，不允许任意代码 | A+D | Phase 2 前 |
| OPEN-07 | Agent 模型和 API | 选择稳定结构化输出模型，并保留 mock | D | Phase 3 前 |
| OPEN-08 | Web/集成阶段主负责人 | 按第一阶段进度再确定 | 全员 | Phase 5 前 |
| OPEN-09 | 目标用户和 Learn Mode 深度 | 学生/初级研究者；解释层不改变底层回测 | 全员 | Phase 1 末 |
| OPEN-10 | User Study 设计 | 5–10 人，任务完成率 + 简化 SUS + 反馈 | Web Owner | Phase 6 前 |
| OPEN-11 | 公共部署方式 | 云端展示层 + 缓存结果；LEAN 可保留本地 Worker | C+Web Owner | Phase 6 前 |
| OPEN-12 | 开源范围与许可证 | 开源框架/示例，不包含受限行情 | 全员 | Phase 7 前 |

---

## 14. 主要风险与处理

| 风险 | 表现 | 处理 |
|---|---|---|
| 本地 LEAN 缺数据 | 代码可编译但无法回测 | 第一阶段优先完成数据需求报告，不盲目下载 |
| QC 与本地不一致 | 同一代码结果明显不同 | 固定版本、数据、模型和配置，逐项对齐 |
| ML 依赖不可用 | QC 能跑、本地 LEAN 失败 | 优先 scikit-learn 可用方案；复杂模型降级 |
| ML 未来泄漏 | 结果异常好 | walk-forward、时间断言、人工复核 |
| Agent 生成代码不稳定 | 频繁编译失败 | 模板优先、API 白名单、有限 Repair |
| Agent 改变策略含义 | 修复后表现突然变化 | Spec 为真源、语义 diff、A/B 复核 |
| 项目范围过大 | 长时间设计通用 DSL | Spec v1 只覆盖 4 基线和 3 候选 |
| 三候选只是换名字 | 逻辑高度重复 | 强制信号来源约束和消融比较 |
| Test 被反复使用 | 越调越好 | 隔离 Test，锁定后只运行一次 |
| Demo 依赖长回测 | 现场超时 | 异步任务、缓存、固定结果快照、备用录像 |
| 文献综述流于拼接 | 只有 8 篇摘要，没有研究空白 | 使用统一 Paper Matrix，并由一人整合论证 |
| 教育功能范围失控 | 为加分开发完整游戏 | Learn Mode 只复用真实结果；Challenge 保持 STRETCH |
| 解释与结果不一致 | LLM 生成听起来合理但无证据的话 | 解释必须绑定 Spec diff、run_id 和指标 |
| 公开部署泄露数据/密钥 | Repo 或云端包含受限资源 | 数据与服务分离，公开前做安全和许可检查 |

削减顺序：

```text
QuantConnect Cloud Provider
→ 任意用户代码上传
→ 多轮复杂讨论
→ 高级前端动画
→ 额外市场/资产
```

不能削减：

- 四个基线；
- 三类候选；
- Strategy Spec → LEAN 代码；
- 本地 LEAN 真实回测；
- 风险与样本外验证；
- Web 主闭环。

---

## 15. 给 AI/LLM 的工作规则

任何协助 AlphaForge 的 AI 都必须：

1. 把本文档最新流程视为当前项目事实；
2. 不把旧版“1 传统 + 1 ML + 1 Defensive”等基线方案继续当成当前决定；
3. 四个基线固定为 2 Traditional + 2 ML；
4. 优化阶段必须分别生成 Traditional、ML、Hybrid 三类候选；
5. 把 Strategy Spec 当作策略语义真源；
6. 不允许 Code Agent 自行改变 Spec；
7. 基于真实 LEAN 日志修复，不虚构通过结果；
8. 不使用未来数据，不用 Test 调参；
9. 所有策略必须遵守统一回测协议；
10. 修改接口时同步 Pydantic Schema、示例和测试；
11. 优先完成当前 Phase，不主动扩大到 STRETCH；
12. 对 OPEN 项明确写出假设，不能当作 FROZEN；
13. 如果本地 LEAN 或数据条件不满足，要报告具体阻塞；
14. 不保证策略盈利，不把结果表述为投资建议；
15. 任何“改进”都要同时说明收益、回撤、波动、成本和稳健性代价；
16. 面向学习者时使用清晰语言解释指标，但不能把风险教育写成投资建议；
17. 解释内容必须引用 Strategy Spec diff、run_id 或真实指标；
18. 研究结论和“创新/首次”等表述必须有论文证据；
19. 使用外部代码、论文和 AI 生成内容时提醒团队记录来源；
20. 不为了 Bonus 擅自加入与核心问题无关的 RAG、游戏或多模态模块。

给新 AI 的推荐提问模板：

```text
你正在协助 AlphaForge 项目。请先阅读 ALPHAFORGE_TEAM_CONTEXT.md。
当前阶段：Phase X
我的成员角色：Member A/B/C/D
本次目标：
相关文件：
已有运行结果或错误日志：
必须保持的 FROZEN 决策：
期望交付物：代码 / 测试 / 文档 / 实验结果

请先指出任务依赖和验收标准，再在当前范围内完成工作。
如果发现与本文档冲突，必须明确指出，不得静默改变架构。
```

---

## 16. Decision Log

| 日期 | 决策 | 状态 | 影响 |
|---|---|---|---|
| 2026-07-17 | 使用本地 LEAN 作为主要回测执行引擎 | FROZEN | QuantConnect Cloud 降为可选 Provider |
| 2026-07-17 | Strategy Spec 是策略 Source of Truth | FROZEN | `main.py` 是生成产物，不是唯一策略定义 |
| 2026-07-17 | 四个基线为两个传统 + 两个 ML | FROZEN | 替代旧版四基线组合 |
| 2026-07-17 | 优化必须输出传统、ML、混合三类候选 | FROZEN | 三类候选分别生成代码和回测 |
| 2026-07-17 | 第一阶段按策略传统/ML、LEAN、Agent 架构四线并行 | FROZEN | 对应当前四人真实分工 |
| 2026-07-17 | 第一阶段先打通兼容性和共同 Schema | FROZEN | Web 和完整多 Agent 不阻塞技术验证 |
| 2026-07-18 | 使用最新 100 分评分标准替代旧版 50/30/10 映射 | FROZEN | 文献、问题、创新、UX、实验和展示均成为独立交付 |
| 2026-07-18 | 增加 Learn & Explain Mode，但不改变核心优化架构 | WORKING | 强化教育价值、实际用途、XAI 和 UX |
| 2026-07-18 | 将 Literature Review 设为全组共同任务 | FROZEN | 满足 8/5/2/1 文献最低要求 |
| 2026-07-18 | 优先争取 Multi-Agent、XAI、Docker、GitHub、User Study 和 Cloud Demo 加分 | WORKING | 与现有架构一致，避免无关功能膨胀 |

---

## 17. 第一阶段结束时，团队应该能说清楚的七句话

1. 我们有两个传统和两个 ML 基线，而且都能用 QuantConnect Python 形式表达；
2. 我们知道这四份代码在本地 LEAN 中哪些能运行、哪些需要修改以及为什么；
3. 我们知道 2015 年至当前回测需要哪些数据、目前具备哪些、缺哪些；
4. 我们已经定义了 Agent 如何根据五组结果生成传统、ML、混合三种 Strategy Spec；
5. 我们已经统一 Strategy Manifest、LEAN Environment 和 Backtest Result，下一阶段可以真正集成；
6. 我们已经完成至少 8 篇论文的比较矩阵，并能用文献解释研究空白；
7. 我们已经说明目标用户、数据来源、许可限制、实际价值和教育价值。

只要这七句话都有文件和运行证据，第一阶段就算成功。否则，不应急着进入复杂前端或多轮 Agent 优化。

---

## 18. 文献综述与研究定位（最新标准新增）

### 18.1 文献最低门槛

最终文献包必须满足 `8/5/2/1`：

```text
至少 8 篇研究论文
其中至少 5 篇发表于最近五年
至少 2 篇来自权威出版机构
至少 1 篇为 survey paper
```

Literature Review 必须回答：

- 现有量化策略和 ML 预测如何工作；
- 现有自动策略优化方法的优点和限制；
- Financial LLM/Multi-Agent 已经解决了什么；
- LLM 代码生成为什么会有执行、安全和语义一致性问题；
- 现有研究在风险治理、可复现回测和教育解释上还有什么空白；
- AlphaForge 的三项创新如何对应这些空白。

### 18.2 推荐研究论点

以下只是待文献验证的工作假设，不能在没有证据时直接宣称：

> 现有研究往往分别关注金融预测、组合优化、LLM Agent 或代码生成；AlphaForge 尝试通过受控 Strategy Spec，把三路线候选设计、风险否决、代码生成和真实 LEAN 证据连接成可审计闭环，同时为学习者解释优化过程。

### 18.3 创新必须用实验支撑

核心消融：

- 单 Agent vs Multi-Agent；
- 无 Risk Reviewer vs 有 Risk Reviewer；
- 单一候选 vs Traditional/ML/Hybrid 三路线；
- 自由生成 Python vs Strategy Spec 约束生成；
- 无解释层 vs Learn & Explain Mode 的用户理解差异。

---

## 19. 教育意义与用户体验设计

### 19.1 Learn & Explain Mode 的最小功能

| 功能 | 教育意义 | 实现原则 |
|---|---|---|
| Metric Cards | 解释 Sharpe、Drawdown、Volatility、Turnover | 使用真实结果和简短例子 |
| Strategy Diff | 展示 Agent 改了哪些 Spec 字段 | 可点击查看修改前后 |
| Why This Change | 解释优化假设 | 与 Agent reason 和证据绑定 |
| Risk Trade-off | 展示收益提高是否以风险为代价 | 同时显示收益、回撤、费用 |
| Rejection Story | 解释候选为什么被 Risk Agent 拒绝 | 强调“高收益不等于好策略” |
| What-if Lab | 改变费用、回撤阈值、市场过滤 | 使用有限预设，避免任意搜索 |
| Overfitting Warning | 解释 Train/Validation/Test 和泄漏 | 通过失败案例教学 |
| Reproducibility Card | 展示数据、代码、模型和 Prompt 版本 | 培养实验规范意识 |

### 19.2 轻量 Serious Game 机会（STRETCH）

不开发独立交易游戏，只增加一个 `Strategy Challenge`：

1. 隐藏最终结果，向用户展示三种候选的策略描述；
2. 用户选择认为最稳健的候选并说明原因；
3. 系统揭示 LEAN 的样本外结果和 Risk Agent 判断；
4. 用户获得关于收益—风险、过拟合和成本的反馈。

这可以增强教育性和互动性，但只能在核心 Web 闭环稳定后开发。

### 19.3 用户研究

建议邀请 5–10 名目标用户完成：

- 创建并运行一个初始策略；
- 找出四个基线中最大回撤最低者；
- 解释一个 Agent 修改；
- 判断一个候选被拒绝的原因；
- 使用 What-if Lab 比较费用变化。

记录：

- 任务完成率；
- 完成时间；
- 错误数量；
- 简化 SUS 或满意度；
- 3–5 个开放反馈；
- 根据反馈做了哪些 UI 修改。

---

## 20. 实际用途与责任边界

### 20.1 可落地的实际用途

- **课程教学：** 展示传统、ML 和混合策略在同一回测规则下的差异；
- **策略研究：** 快速生成受控候选并保留完整实验记录；
- **代码验证：** 检查 AI 生成策略能否真正被 LEAN 执行；
- **风险教育：** 让用户看到收益、回撤、成本和过拟合之间的关系；
- **团队协作：** 用 Strategy Spec、run_id 和 manifest 统一研究交接；
- **研究原型：** 为 Multi-Agent 风险治理和代码生成成功率提供实验平台。

### 20.2 产品责任边界

AlphaForge 是教育、研究和决策支持工具：

- 不保证收益；
- 不构成投资建议；
- 不连接真实资金；
- 不隐藏失败策略；
- 不以 Test 结果反复调参；
- 必须显示数据和模型局限；
- 必须允许输出“没有稳健改进”。

---

## 21. 加分点实施优先级

最新指南最多提供 5 分 Bonus。优先选择与主架构自然一致的项目：

| 优先级 | 加分点 | AlphaForge 实施方式 | 是否改变主框架 |
|---:|---|---|---|
| 1 | Multi-Agent AI | 三类 Designer + Risk/Robustness/Decision + 消融 | 否，核心已有 |
| 2 | Explainable AI | Spec diff、风险 trade-off、接受/拒绝证据卡片 | 否，增加解释层 |
| 3 | Docker | API/Web/LEAN Worker 可复现部署 | 否，工程化 |
| 4 | GitHub Repository | README、架构、测试、Issues/PR、Release | 否，工程证据 |
| 5 | User Study | 5–10 人任务测试和 Learn Mode 前后对比 | 否，增强 UX/教育 |
| 6 | Cloud Deployment | 部署 Web/缓存 Demo；LEAN Worker 可本地 | 否，展示增强 |
| 7 | Open-source Release | 开源框架、Spec 和示例，不发布受限数据 | 否，需许可检查 |
| 8 | Serious Game | Strategy Challenge | 否，但仅 STRETCH |

当前不建议加入：

- 与核心需求无关的 RAG；
- 多模态输入；
- 完整游戏系统；
- 为了凑模型数量增加无用 AI 模块。

加分项必须提供真实证据，例如 Docker 启动命令、用户研究结果、公开 Release 或消融实验，不能只写在 PPT 中。

---

## 22. Proposal、数据伦理、学术诚信与 Showcase

### 22.1 Proposal（最多 15 页）

建议结构：

1. Title + Team；
2. Problem Significance；
3. Target Users and Current Workflow；
4. Motivation；
5. Initial Literature Review；
6. Research Gap；
7. Innovation；
8. End-to-End Workflow；
9. AI/System Architecture；
10. AI/ML Methods；
11. Data Sources and Ethics；
12. Initial Progress；
13. Evaluation Plan；
14. Timeline, Roles and Resources；
15. Risks and Expected Outcome。

### 22.2 数据与伦理

必须记录：

- 数据来源；
- 收集方法；
- 数据清洗；
- 复权、Ticker mapping 和公司行为；
- 数据覆盖和缺失；
- 许可与再分发限制；
- 哪些数据不会提交到公开仓库。

### 22.3 AI 使用和学术诚信

必须记录：

- 使用了哪些 AI 工具；
- AI 用于代码、文档还是研究辅助；
- 谁复核了生成代码；
- 如何证明团队理解代码；
- 外部代码、论文和模板的引用；
- 团队自己的设计、实验和分析贡献。

### 22.4 Final Showcase

最终必须准备：

- 可持续运行、访客可交互的应用；
- Poster：Problem、Innovation、AI Architecture、Results、QR；
- QR Code 链接 GitHub Repository、Streamlit Application、Demo Video、Project Website；
- 现场主 Demo；
- 缓存结果和离线备用；
- 展会硬件、网络和恢复方案。

---

## 23. 项目最终成功标准

AlphaForge 最终成功不等于“得到最高 Sharpe”。项目需要同时证明：

1. 解决了明确的金融策略研究与风险理解问题；
2. 有合格文献综述支持研究空白；
3. Multi-Agent、Strategy Spec 和 LEAN 闭环具有可验证创新；
4. 至少两种 AI 技术被正确实现并公平评估；
5. 四基线和三候选可在统一环境运行；
6. 用户能够理解修改、风险和失败原因；
7. 实验包含样本外、鲁棒性、消融和失败案例；
8. Web 应用稳定、可交互并完成用户测试；
9. 数据、代码、模型、Prompt 和结果可追溯；
10. Poster、QR、视频、仓库和项目主页可用于 Showcase；
11. 所有来源、AI 使用和许可限制均已披露；
12. 如果没有稳健改进，系统能够诚实拒绝所有候选。
