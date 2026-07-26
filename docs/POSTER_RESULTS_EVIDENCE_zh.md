# AlphaForge Poster Results 数据统计与证据

> 文档用途：为项目 Poster 的 **Results** 部分提供可复核的数据统计、代表案例与结论边界。
> 统计日期：2026-07-26
> 数据来源：`backend/workspace/run_history/`

## 1. 研究问题

本次统计希望回答以下问题：

1. AlphaForge 是否能够在多次迭代中改善 AI 生成策略？
2. Critic、Best-of-3 选择和历史冠军保留机制是否具有实际作用？
3. Traditional、Machine Learning 和 Hybrid 三类策略的优化效果是否存在差异？
4. 历史记录中表现最好的三次优化分别是什么？

本报告关注的是系统的**历史回测优化能力**，而不是对未来投资收益作出保证。

---

## 2. 数据范围与统计口径

### 2.1 数据范围

**原始数据位置：**

```text
backend/workspace/run_history/*.json
```

每个 JSON 文件对应一次 AlphaForge Run。文件中保存了该次运行的实验设置、三个 AI 策略轨道、各轨道的 Trial 记录、LEAN 回测指标、Critic 反馈及最终入选策略。

本报告逐个读取该目录中的 JSON 文件，没有使用前端截图、人工录入结果或模拟数据。目录中共有 23 份可读取的 Run 记录：

- 2 份为旧版 Schema 2.0；
- 21 份为当前架构使用的 Schema 3.0；
- Schema 3.0 记录中包含 61 条 AI 策略轨道；
- 其中 58 条轨道至少包含两次有效回测，因此可用于优化前后比较。

**筛选过程：**

```text
23 份历史 Run
  → 排除 2 份旧版 Schema 2.0
21 份当前架构 Run
  → 提取 Traditional、ML、Hybrid 候选
61 条 AI 策略轨道
  → 要求至少有 2 次有效 Trial
58 条可进行优化前后比较的轨道
```

每条 AI 策略轨道属于以下类别之一：

- Traditional；
- Machine Learning；
- Hybrid。

### 2.2 有效回测

**数据来源：** 每个 Candidate 的 `iterations[].state` 和 `iterations[].summary` 字段。

一次回测需要同时满足以下条件，才被纳入有效样本：

- 回测状态为 `completed`；
- Sharpe Ratio、CAGR 和 Maximum Drawdown 均可读取；
- `total_orders > 0`，即策略产生了实际订单。

对应的字段读取关系如下：

| 报告指标 | JSON 字段 |
|---|---|
| 回测状态 | `candidates[].iterations[].state` |
| Sharpe Ratio | `candidates[].iterations[].summary.sharpe_ratio` |
| CAGR | `candidates[].iterations[].summary.cagr` |
| Maximum Drawdown | `candidates[].iterations[].summary.maximum_drawdown` |
| Ending Equity | `candidates[].iterations[].summary.end_equity` |
| 实际订单数 | `candidates[].iterations[].summary.total_orders` |

### 2.3 优化前后比较

**统计单位：** 一条 AI 策略轨道，例如某一个 Run 中的 ML Candidate。

对于每条可比较轨道：

- **优化前**：该轨道的 Trial 1；
- **优化后**：由 `current_round_best_iteration` 或旧记录中的 `best_iteration` 指定的本轮最佳策略；
- 若后续策略没有改善，系统可以继续保留 Trial 1。

对于指标 \(M\)，计算方法为：

```text
绝对变化 = M_selected − M_trial1
CAGR 提升（百分点） = (CAGR_selected − CAGR_trial1) × 100
回撤改善（百分点） = (MDD_trial1 − MDD_selected) × 100
期末资产提升率 = (Equity_selected ÷ Equity_trial1 − 1) × 100%
```

Maximum Drawdown 越低越好，因此其“改善”使用 Trial 1 减去入选策略；表格中的正数代表回撤下降。

因此，本报告同时统计：

1. 每次后续重写相对于 Trial 1 的原始表现；
2. Best-of-3 选择后的最终表现；
3. 跨 Battle 轮次的历史冠军变化。

### 2.4 实质性改善

**数据来源：** 上述58条轨道中 Trial 1 与本轮入选策略的配对差值。

满足以下任一条件，即记为一次“实质性改善”：

- Sharpe Ratio 增加至少 0.02；
- CAGR 增加至少 1 个百分点；
- Maximum Drawdown 降低至少 2 个百分点。

该阈值是本报告用于描述效果的统计口径，不是系统内部的唯一评分规则。

### 2.5 平均值、中位数和置信区间

- **平均变化**：先在每条轨道内部计算 Trial 1 到入选策略的变化，再对全部轨道求算术平均；
- **中位数变化**：对全部轨道的变化值取中位数，用于观察典型轨道，而不是被少量大幅提升案例主导；
- **95% Cluster Bootstrap 区间**：以 Run 为聚类单位进行10,000次有放回重采样，同一个 Run 中的三个策略轨道一起被抽取，从而减少把同一 Run 的相关轨道误当成完全独立样本的问题；
- Bootstrap 使用固定随机种子 `3022`，便于复算。

这些区间是对当前历史样本的描述性不确定性估计，不代表正式的样本外收益置信区间。

---

## 3. 总体优化结果

**数据来源：** 21份 Schema 3.0 Run 中，58条至少包含两次有效 Trial 的 AI 策略轨道。
**比较对象：** 每条轨道的 Trial 1 与该轮最终入选 Trial。
**统计方法：** 先计算每条轨道的配对变化，再计算58条变化值的平均数、中位数和以 Run 聚类的 Bootstrap 区间。
**注意：** 这里不是把不同股票池策略的绝对收益直接相减，而是在同一 Run、同一股票池、同一回测期间内比较优化前后，再汇总变化幅度。

将58条可比较轨道的 Trial 1 与系统最终选中的本轮最佳策略进行比较：

| 指标 | 平均变化 | 中位数变化 | 95% Cluster Bootstrap 区间 |
|---|---:|---:|---:|
| Sharpe Ratio | **+0.083** | +0.006 | +0.055 ～ +0.112 |
| CAGR | **+1.79 个百分点** | +0.07 个百分点 | +1.13 ～ +2.48 个百分点 |
| Maximum Drawdown | **降低 1.36 个百分点** | 0.00 | 降低 0.49 ～ 2.27 个百分点 |
| Ending Equity | **+10.04%** | +0.29% | +6.15% ～ +14.04% |

进一步统计：

- 58条轨道中，32条最终选择了 Trial 2 或 Trial 3，占 **55.2%**；
- 29条轨道出现实质性改善，占 **50.0%**；
- 其余轨道由系统保留较早的更优候选，避免被较差的后续结果覆盖。

### 可用于 Poster 的核心数字

**数据来源与方法：** 与本节主表相同。其中“选择后续 Trial”通过比较 `current_round_best_iteration`/`best_iteration` 与 Trial 1 的编号计算；“实质性改善”依据第2.4节定义计算。

| 核心指标 | 结果 |
|---|---:|
| 可比较 AI 优化轨道 | 58 |
| 选择后续 Trial 的轨道 | 32（55.2%） |
| 产生实质性改善的轨道 | 29（50.0%） |
| 平均 Sharpe 提升 | +0.083 |
| 平均 CAGR 提升 | +1.79 个百分点 |
| 平均最大回撤改善 | -1.36 个百分点 |
| 平均期末资产提升 | +10.04% |

---

## 4. 分策略类型的优化效果

**数据来源：** 上述58条可比较轨道，按照 `candidates[].track` 分组。
**样本构成：** Traditional 21条、ML 19条、Hybrid 18条。
**统计方法：** 每个类别内部，对 Trial 1 到入选策略的配对变化求算术平均。
**为何各组样本数不同：** 只有至少两次有效 Trial 的轨道才能进行前后比较；部分轨道只完成了一次有效回测，因此未进入本表。

| AI 策略类型 | 样本数 | 平均 Sharpe 提升 | 平均 CAGR 提升 | 平均回撤改善 | 平均期末资产提升 |
|---|---:|---:|---:|---:|---:|
| Traditional | 21 | +0.083 | +1.45 pp | -1.37 pp | +8.11% |
| Machine Learning | 19 | **+0.116** | **+2.50 pp** | **-1.97 pp** | **+14.74%** |
| Hybrid | 18 | +0.049 | +1.45 pp | -0.69 pp | +7.33% |
| **Overall** | **58** | **+0.083** | **+1.79 pp** | **-1.36 pp** | **+10.04%** |

当前历史样本中：

- Machine Learning 轨道从多轮参数优化中获益最明显；
- Traditional 轨道也获得了较稳定的平均改善；
- Hybrid 的平均改善相对较小，反映出模型信号、传统信号和组合权重之间存在更复杂的参数耦合。

---

## 5. Critic 与策略选择机制的作用

**数据来源：** 21份 Schema 3.0 Run 中所有有效的 Trial 2 和 Trial 3，共114次后续参数尝试。
**比较方法：** 每一次 Trial 2/3 均与其所在轨道的 Trial 1 比较，而不是只保留成功的尝试。
**判断顺序：** 优先比较 Sharpe；Sharpe相同时比较CAGR；两者仍相同时选择Maximum Drawdown更低者。
**目的：** 检查 Designer 的每次重写是否天然改善策略，以及 Critic 和候选选择机制是否确有必要。

如果把所有 Trial 2 和 Trial 3 单独视为一次新的参数尝试，共有114次有效后续尝试：

| 后续尝试相对 Trial 1 的表现 | 次数 | 比例 |
|---|---:|---:|
| 更好 | 53 | 46.5% |
| 基本相同 | 12 | 10.5% |
| 更差 | 49 | 43.0% |

如果直接使用每条轨道的最后一次回测，而不进行最佳候选选择，则58条轨道中：

- 28条改善；
- 5条不变；
- 25条退化。

这说明 LLM 并不能保证每次重写都改善策略。AlphaForge 的优化效果来自完整的闭环，而不只是一次代码或参数生成：

```text
Designer 生成结构化策略参数
        ↓
模板编译为受控 LEAN 策略
        ↓
LEAN 执行真实回测
        ↓
Critic 根据指标和行为证据评价
        ↓
Designer 根据 Critic 意见重写参数
        ↓
Best-of-3 选择 + 历史冠军保留
```

因此，Critic 和选择机制承担了两项关键功能：

1. 指导 Designer 进行有证据支撑的下一次参数调整；
2. 阻止较差的后续尝试覆盖已有的更优策略。

---

## 6. 跨对战轮次的优化效果

**数据来源：** `battle_id` 相同且包含至少两个 Round 的 Run。当前共有8场多轮 Battle，每场分别观察 Traditional、ML 和 Hybrid 三条轨道，因此形成24条跨轮次比较。
**优化前：** 每场 Battle 第一轮结束后保存的轨道冠军，即 Candidate 顶层 `summary`。
**优化后：** 同一 Battle 当前最后一轮结束后保存的轨道冠军。
**统计方法：** 按 `(battle_id, track)` 配对，比较第一轮冠军和最后一轮冠军；不是比较某一轮内部未经选择的最后一次 Trial。
**设置一致性：** 同一 Battle 的股票池、回测日期、初始资金、基准、手续费和滑点由 Battle 设置固定，跨轮比较处于同一实验条件下。

当前历史记录中有8场包含多个轮次的 Battle，共形成24条可比较的 AI 策略轨道。

从第一轮冠军到该场 Battle 的最后一轮冠军：

| 结果 | 轨道数 | 比例 |
|---|---:|---:|
| Sharpe 提升 | **17** | **70.8%** |
| Sharpe 保持 | **7** | **29.2%** |
| Sharpe 下降 | **0** | **0.0%** |

跨轮次平均变化：

| 指标 | 平均变化 |
|---|---:|
| Sharpe Ratio | **+0.100** |
| CAGR | **+2.53 个百分点** |
| Maximum Drawdown | **降低 0.64 个百分点** |
| Ending Equity | **+13.61%** |

这些结果支持历史冠军保留机制的设计：当新一轮候选不能超过已有策略时，系统继续使用原冠军，从而避免跨轮次的冠军 Sharpe 发生退化。

---

## 7. 最优 AI 策略与全部 Baseline 的比较

### 7.1 数据来源与比较方法

**数据来源：**

```text
backend/workspace/run_history/*.json
  └─ battle_analysis.judge.scorecards
```

本节使用21份 Schema 3.0 Run 中已经保存的策略计分卡。每份纳入统计的 Run 均满足：

- 四个 Baseline 均存在且通过资格检查；
- 至少有一个 AI Candidate 通过资格检查；
- 计分方法为 `deterministic_weighted_score_v2`。

**“当次最优 AI 策略”的定义：**

在同一个 Run 的 Traditional、ML 和 Hybrid 三个合格 AI Candidate 中，选择综合评分最高者。

**“超过所有 Baseline”的定义：**

先在 Momentum Rank、Mean Reversion、Gradient Boosting 和 Hybrid ML + Minimum Variance 四个 Baseline 中找出综合评分最高者。如果当次最优 AI 的综合评分高于这个 Baseline Leader，则该 AI 同时高于其余三个分数更低的 Baseline，因此记为“超过所有 Baseline”。

```text
AI champion score = max(Traditional AI, ML AI, Hybrid AI)
Baseline leader score = max(4 baseline scores)

超过所有 Baseline ⇔ AI champion score > Baseline leader score
```

项目综合评分的权重如下：

| 评分组成 | 权重 |
|---|---:|
| Sharpe Ratio | 35% |
| CAGR | 30% |
| Drawdown Control | 15% |
| Volatility Control | 5% |
| Cost Efficiency | 5% |
| Execution Evidence | 5% |
| Explainability | 5% |

各组成项先在同一次 Run 的合格策略中标准化为0–100分，再按照上述权重计算综合评分。因此，本节比较的是项目真实评分规则下的风险—收益—成本综合表现，不是只比较 CAGR。

### 7.2 按 Run/Round 统计

**统计单位：** 一次 Run，即某一场 Battle 的某一个 Round。
**样本数：** 21个具有四个有效 Baseline 和有效 AI Candidate 的 Run。
**计算方法：** 在每个 Run 内比较 AI Champion Score 和 Baseline Leader Score，然后统计 AI 胜出的次数。

| 结果 | 次数 | 比例 |
|---|---:|---:|
| 最优 AI 综合评分超过全部 Baseline | **9** | **42.9%** |
| 最优 AI 未超过最佳 Baseline | 12 | 57.1% |
| 总计 | 21 | 100% |

在9次胜出记录中：

- AI 相对最佳 Baseline 的平均评分优势为 **19.73分**；
- 评分优势中位数为 **24.50分**；
- 最小优势为0.14分；
- 最大优势为31.34分。

具体胜出记录如下：

| Run ID | Battle / Round | AI Champion | AI Score | Best Baseline | Baseline Score | 领先 |
|---|---|---|---:|---|---:|---:|
| `forge-23c3b6455af3` | `battle-8b2cca8bf768` / R1 | Traditional | 91.66 | Gradient Boosting | 74.96 | +16.70 |
| `forge-31833cbca087` | `battle-491d8e911b40` / R1 | Hybrid | 83.48 | Momentum Rank | 52.14 | +31.34 |
| `forge-322a563c5093` | `battle-563b2062055b` / R2 | Hybrid | 92.16 | Momentum Rank | 67.66 | +24.50 |
| `forge-359b55ca1123` | `battle-491d8e911b40` / R3 | Hybrid | 82.19 | Momentum Rank | 51.36 | +30.83 |
| `forge-7af65532c60f` | `battle-8b2cca8bf768` / R2 | ML | 79.65 | Gradient Boosting | 77.82 | +1.83 |
| `forge-92c19baa2d2e` | `battle-d1a923ee0207` / R3 | ML | 73.16 | Gradient Boosting | 73.02 | +0.14 |
| `forge-9366155247ad` | `battle-491d8e911b40` / R2 | Hybrid | 82.32 | Momentum Rank | 51.52 | +30.80 |
| `forge-98a22e9bf145` | `battle-8b2cca8bf768` / R3 | Traditional | 91.68 | Gradient Boosting | 75.04 | +16.64 |
| `forge-e24ccb2b0ae3` | `battle-563b2062055b` / R1 | Hybrid | 92.28 | Momentum Rank | 67.48 | +24.80 |

9次胜出中，AI Champion 的类别构成为：

- Hybrid：5次；
- Traditional：2次；
- ML：2次。

### 7.3 去除同一 Battle 重复轮次后的统计

同一个 Battle 的不同 Round 会重复使用第一轮的 Baseline 结果，并允许历史 AI 冠军继续保留。因此，直接把21个 Round 全部视为相互独立实验，会重复计算部分 Baseline 和 AI 冠军。

为给出更保守的结果，本报告进一步：

1. 按 `battle_id` 分组；
2. 每场 Battle 只保留最后一个已完成 Round；
3. 比较该场最终 AI Champion 与四个 Baseline。

**数据来源：** 8个不同的多轮 Battle。
**统计结果：**

| Battle 级别结果 | 场数 | 比例 |
|---|---:|---:|
| 最终最优 AI 综合评分超过全部 Baseline | **4** | **50.0%** |
| 最终最优 AI 未超过最佳 Baseline | 4 | 50.0% |
| 总计 | 8 | 100% |

因此，可以使用两种互补表述：

- 按系统运行轮次统计：最优 AI 在 **9/21（42.9%）** 的 Run 中超过所有 Baseline；
- 按独立 Battle 的最终结果统计：最优 AI 在 **4/8（50.0%）** 的 Battle 中超过所有 Baseline。

Poster 如果只能保留一个数字，建议使用更不容易重复计数的 **4/8 场 Battle（50.0%）**；如果要展示系统每轮的实际表现，可以使用 **9/21 个 Run（42.9%）**，但必须注明统计单位是 Run/Round。

### 7.4 按单项指标检查“超过”

综合评分允许不同指标之间进行权衡。为避免把“综合评分胜出”误解成“所有单项指标均为第一”，本报告还直接比较了 AI Champion 和四个 Baseline 的原始指标。

**数据来源：** 与第7.2节相同的21个 Run。
**计算方法：**

- Sharpe领先：AI Sharpe 大于四个 Baseline Sharpe 的最大值；
- CAGR领先：AI CAGR 大于四个 Baseline CAGR 的最大值；
- 回撤领先：AI Maximum Drawdown 小于四个 Baseline 回撤的最小值。

| AI Champion 的单项表现 | Run 数 | 比例 |
|---|---:|---:|
| Sharpe 高于全部 Baseline | **10** | **47.6%** |
| CAGR 高于全部 Baseline | **5** | **23.8%** |
| Maximum Drawdown 低于全部 Baseline | **2** | **9.5%** |
| Sharpe 与 CAGR 同时高于全部 Baseline | **5** | **23.8%** |
| Sharpe、CAGR、回撤三项同时全面领先 | **0** | **0.0%** |

这个结果说明：

- AI 策略较常在 Sharpe，即风险调整后收益上超过四个 Baseline；
- 部分 AI 策略以更高回撤换取更高 Sharpe 或 CAGR；
- 当前样本中还没有一个 AI 策略同时在 Sharpe、CAGR 和 Maximum Drawdown 三项上严格支配所有 Baseline；
- 因此应将结果描述为“综合表现超过全部 Baseline”，而不是“在所有指标上全面超过 Baseline”。

### 7.5 可用于 Poster 的表述

中文：

> 按项目的确定性综合评分标准，最优AI策略在21个有效Run中的9次超过全部四个Baseline；按独立Battle的最终结果去重后，AI在8场对战中的4场取得领先。

英文：

> Under the deterministic composite scoring framework, the best AI strategy outperformed all four baselines in 9 of 21 valid runs. After deduplicating repeated rounds and retaining only each battle's final result, AI led in 4 of 8 battles.

---

## 8. 三个最佳优化案例

**数据来源：** 第3节使用的58条可比较轨道及其原始 JSON。
**排序方法：** 按 Trial 1 到本轮入选策略的 Sharpe 绝对增量从高到低排序。
**入选要求：** 除Sharpe提升外，CAGR必须提高且Maximum Drawdown必须下降，以避免选择只改善单一指标、却明显牺牲其他指标的案例。
**复核方式：** 每个案例均给出 Run ID、股票池、回测区间、Trial编号和原始文件位置。

以下案例按照 **Sharpe Ratio 的绝对提升幅度** 排序，并同时报告 CAGR、Maximum Drawdown 和 Ending Equity，避免只依据单一收益指标选择案例。

### 8.1 Top 1：Machine Learning Strategy

**数据读取位置：**

```text
backend/workspace/run_history/forge-77e1629c4632.json
  └─ candidates[track="ML"].iterations[Trial 1 / Trial 3].summary
```

**Run ID：** `forge-77e1629c4632`
**Battle：** `battle-5166bf1661d4`，Round 1
**最佳版本：** Trial 3
**股票池：** MSFT、GOOGL、AMZN、LLY、JPM、WMT、AAPL、NVDA
**回测期间：** 2017-01-02 至 2024-12-31

| 指标 | Trial 1 | Trial 3 | 改善 |
|---|---:|---:|---:|
| Sharpe Ratio | 0.619 | **1.089** | **+0.470 / +75.9%** |
| CAGR | 15.53% | **24.22%** | **+8.68 pp** |
| Maximum Drawdown | 39.0% | **27.2%** | **降低 11.8 pp** |
| Ending Equity | $317,508 | **$566,988** | **+78.57%** |

本案例的计算示例：

```text
Sharpe 增量 = 1.089 − 0.619 = 0.470
CAGR 增量 = 24.215% − 15.533% = 8.682 个百分点
回撤改善 = 39.0% − 27.2% = 11.8 个百分点
期末资产提升 = 566,988.38 ÷ 317,507.74 − 1 = 78.57%
```

主要参数及机制变化：

- 模型由 Ridge 改为 Gradient Boosting；
- 预测周期由21天缩短至10天；
- Pooled Training Rows 由360调整为180；
- Volatility Window 由63天调整为21天。

该案例体现了 Critic 在原有模型机制可能达到瓶颈时，推动 Designer 更换模型结构的能力。

原始记录：`backend/workspace/run_history/forge-77e1629c4632.json`

### 8.2 Top 2：Machine Learning Strategy

**数据读取位置：**

```text
backend/workspace/run_history/forge-31833cbca087.json
  └─ candidates[track="ML"].iterations[Trial 1 / Trial 3].summary
```

**Run ID：** `forge-31833cbca087`
**Battle：** `battle-491d8e911b40`，Round 1
**最佳版本：** Trial 3
**股票池：** MSFT、GOOGL、AMZN、LLY、CAT、JPM、WMT
**回测期间：** 2020-01-02 至 2024-12-31

| 指标 | Trial 1 | Trial 3 | 改善 |
|---|---:|---:|---:|
| Sharpe Ratio | 0.560 | **0.925** | **+0.365 / +65.2%** |
| CAGR | 12.82% | **17.33%** | **+4.52 pp** |
| Maximum Drawdown | 27.7% | **24.3%** | **降低 3.4 pp** |
| Ending Equity | $182,789 | **$222,458** | **+21.70%** |

本案例的计算示例：

```text
Sharpe 增量 = 0.925 − 0.560 = 0.365
CAGR 增量 = 17.334% − 12.816% = 4.518 个百分点
回撤改善 = 27.7% − 24.3% = 3.4 个百分点
期末资产提升 = 222,458.16 ÷ 182,789.15 − 1 = 21.70%
```

主要参数及机制变化：

- Top-K 由4增加至7，降低个股集中度；
- Minimum Variance Blend 由0.35提高至0.70；
- 组合年化波动率由12.1%下降至10.4%；
- Portfolio Turnover 由2.16%下降至0.73%。

该案例体现了通过分散化和更强风险配置改善风险调整后收益的过程。

原始记录：`backend/workspace/run_history/forge-31833cbca087.json`

### 8.3 Top 3：Hybrid Strategy

**数据读取位置：**

```text
backend/workspace/run_history/forge-72545879de88.json
  └─ candidates[track="Hybrid"].iterations[Trial 1 / Trial 2].summary
```

**Run ID：** `forge-72545879de88`
**Battle：** `battle-04672176f6db`，Round 2
**最佳版本：** Trial 2
**股票池：** MSFT、AAPL、NVDA、GOOGL、AMZN
**回测期间：** 2020-01-02 至 2024-12-31

| 指标 | Trial 1 | Trial 2 | 改善 |
|---|---:|---:|---:|
| Sharpe Ratio | 0.790 | **1.106** | **+0.316 / +40.0%** |
| CAGR | 23.25% | **33.74%** | **+10.49 pp** |
| Maximum Drawdown | 36.1% | **30.8%** | **降低 5.3 pp** |
| Ending Equity | $284,567 | **$428,107** | **+50.44%** |

本案例的计算示例：

```text
Sharpe 增量 = 1.106 − 0.790 = 0.316
CAGR 增量 = 33.741% − 23.255% = 10.486 个百分点
回撤改善 = 36.1% − 30.8% = 5.3 个百分点
期末资产提升 = 428,107.41 ÷ 284,567.32 − 1 = 50.44%
```

主要参数及机制变化：

- Ridge Alpha 由1.0提高至10.0，加强模型正则化；
- Hybrid Model Weight 由0.70降低至0.35；
- Maximum Drawdown 风险阈值由25%收紧至20%。

该案例体现了降低模型依赖、加强正则化，并重新平衡 ML 信号与传统信号的优化思路。

原始记录：`backend/workspace/run_history/forge-72545879de88.json`

---

## 9. Poster 可直接引用的结论

**结论的数据基础：**

- “58条轨道”来自当前 Schema 3.0 历史记录中具备至少两个有效 Trial 的轨道；
- “平均提升”来自同一轨道 Trial 1 与本轮入选策略的配对变化；
- “24条跨轮次轨道”来自8场多轮 Battle × 3个 AI Track；
- “没有出现冠军 Sharpe 下降”描述的是第一轮冠军到最后一轮保留冠军的变化，不代表每一次中间 Trial 都没有退化。
- “9/21个Run超过全部Baseline”来自保存的 `deterministic_weighted_score_v2` 计分卡；
- “4/8场Battle超过全部Baseline”对相同 `battle_id` 的重复Round去重，只保留每场Battle的最终结果。

### 9.1 中文

> 在58条可比较的AI优化轨道中，Best-of-3最终策略的Sharpe Ratio平均提高0.083，CAGR平均提高1.79个百分点，Maximum Drawdown平均降低1.36个百分点。在24条跨轮次AI策略轨道中，17条进一步提升，7条保留原有冠军，没有出现冠军Sharpe下降。

> 按项目的确定性综合评分标准，最优AI策略在21个有效Run中的9次超过全部四个Baseline；对重复轮次去重后，AI在8场独立Battle中的4场取得最终领先。

### 9.2 English

> Across 58 comparable AI optimization tracks, the selected Best-of-3 strategy improved the Sharpe ratio by 0.083 and CAGR by 1.79 percentage points on average, while reducing maximum drawdown by 1.36 percentage points. Across 24 multi-round strategy tracks, 17 improved and 7 retained their previous champion, with no decline in champion Sharpe.

> Under the deterministic composite scoring framework, the best AI strategy outperformed all four baselines in 9 of 21 valid runs. After deduplicating repeated rounds, AI achieved the final lead in 4 of 8 independent battles.

### 9.3 推荐的简短标题

中文：

> **多智能体迭代提高了历史回测表现，并通过冠军保留机制避免策略退化**

英文：

> **Multi-agent refinement improved historical backtest performance while champion retention prevented strategy degradation**

---

## 10. 结果解释与研究限制

这些统计结果能够支持以下结论：

- AlphaForge 能够在历史回测中发现优于初始候选的参数或策略结构；
- Critic 能够基于真实回测结果指导后续迭代；
- Best-of-3 和历史冠军保留机制能够减少较差后续尝试造成的性能退化；
- 优化同时体现在 Sharpe、CAGR、Maximum Drawdown 和 Ending Equity，而不只是单一收益指标。

但不能据此声称策略能够保证未来盈利，主要限制包括：

1. Agent 会在同一历史区间上多次迭代，存在样本内选择偏差；
2. Best-of-3 会选择表现最好的候选，因此结果包含选择效应；
3. 最佳案例通常同时修改多个参数，无法将改善严格归因于单一参数；
4. 不同 Battle 的股票池和时间范围可能不同；
5. 仍需通过 hold-out period、walk-forward analysis 和市场扰动实验验证样本外鲁棒性。

因此，建议使用以下准确表述：

> **Historical backtests demonstrate effective strategy refinement and degradation protection.**

不建议使用：

> **The system guarantees superior future investment performance.**

---

## 11. 可复核数据位置

- 全部历史 Run：`backend/workspace/run_history/`
- Top 1：`backend/workspace/run_history/forge-77e1629c4632.json`
- Top 2：`backend/workspace/run_history/forge-31833cbca087.json`
- Top 3：`backend/workspace/run_history/forge-72545879de88.json`

所有结果均来自项目保存的实际 LEAN 回测记录，而非手工构造的演示数据。

### 11.1 复算流程

任何组员均可按照以下步骤复算报告：

1. 遍历 `backend/workspace/run_history/*.json`；
2. 只保留 `schema_version == "3.0"` 的 Run；
3. 遍历每个 Run 的 `candidates`；
4. 在 `iterations` 中保留状态为 `completed`、核心指标存在且 `total_orders > 0` 的 Trial；
5. 只保留至少有两个有效 Trial 的 Candidate；
6. 将第一个有效 Trial 作为优化前结果；
7. 根据 `current_round_best_iteration`，旧记录则根据 `best_iteration`，找到该轮入选策略；
8. 使用第2.3节公式计算每条轨道的指标变化；
9. 对变化值求平均数、中位数，并以 Run 为单位执行 Cluster Bootstrap；
10. 使用 `battle_id` 和 `track` 对多轮记录分组，比较第一轮与最后一轮的 Candidate 顶层 `summary`。

统计逻辑的简化伪代码如下：

```python
for run in schema_3_runs:
    for candidate in run.candidates:
        trials = [
            trial
            for trial in candidate.iterations
            if trial.state == "completed"
            and trial.summary.total_orders > 0
            and core_metrics_are_available(trial.summary)
        ]

        if len(trials) < 2:
            continue

        before = trials[0].summary
        selected = find_selected_trial(
            trials,
            candidate.current_round_best_iteration
            or candidate.best_iteration,
        ).summary

        paired_changes.append(calculate_changes(before, selected))
```

### 11.2 数据快照说明

本报告反映的是2026-07-26读取到的历史目录快照。项目继续产生新 Run 后，样本数和平均结果可能变化。若 Poster 使用本报告中的数字，应保留本统计日期；若历史目录发生新增或删除，应重新运行同一统计流程。
