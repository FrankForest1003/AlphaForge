# AlphaForge Agent 提示词工程与稳定性说明

更新日期：2026-07-23

## 目标

当前阶段的目标不是让大模型“自由写出任何 LEAN 策略”，而是让它在 AlphaForge 已验证的执行边界内稳定地产出三个相互独立、可解释、可运行且可验收的候选：

- Traditional：只使用透明、确定性的市场信号；
- Machine Learning：必须真实训练模型、生成预测并据此选股；
- Hybrid：必须同时保留可解释信号项和真实 ML 预测。

AI 只能看到冻结的 ExperimentContract、RunSettings 和四个公共基线。Human Strategy 的源码、设置、回测结果和教育分析永远不进入 Designer、Repair 或 Acceptance 上下文。

## 历史 Trace 诊断

分析目录：`backend/workspace/forge_traces/`

| 现象 | 历史证据 | 影响 |
|---|---|---|
| 提示上下文过长 | Designer 单次约 217,557 prompt tokens；Repair 约 223k–224k | 关键约束被整本 LEAN 文档稀释，延迟和费用高 |
| ML 零交易 | 多轮运行完成但没有订单、预测或目标仓位 | 只“成功退出”并不代表策略链路成立 |
| API 用法漂移 | `DMatrix` 解包、`TradeBars.end_time`、Symbol 映射 KeyError | 修复 Agent 容易在不同 API 猜测之间来回切换 |
| 验收缺少证据纪律 | 曾根据源码猜测训练时间、样本行数或运行状态 | 产生无法由 Worker 证据支持的结论 |
| 空响应 | Acceptance 曾返回空 content | 一次偶发响应会直接破坏整条候选链 |

2026-07-23 的真实 ML Designer 烟雾测试使用 5 股票公共设置和四个基线摘要，得到 2,413 prompt tokens、3,039 completion tokens；结构化设计包含 5 个特征和 7 段因果链，生成的 9,611 字符源码一次通过静态预检且无警告。它证明提示体积和输出契约已经生效，但不替代真实 LEAN 回测与 Acceptance。

## 新的生成协议

Designer 不再接收完整 LEAN 文档，而接收四类紧凑信息：

1. 版本化 Agent Capability Contract：支持的基类、History 范式、共享调仓器、稳定 ML 子集、证据钩子和常见失败；
2. 当前轨道的 Track Recipe；
3. 已验证可运行的 `UserStrategy` 模板；
4. 公共基线和冻结的 RunSettings。

输出必须同时包含：

- `design.strategy_name`
- `design.track`
- `design.thesis`
- `design.signals`
- `design.features`
- `design.training_plan`
- `design.selection_rule`
- `design.rebalance_rule`
- `design.risk_controls`
- `design.causal_chain`
- `source_code`

Traditional 的 `training_plan` 必须为空且不得出现模型训练；ML 和 Hybrid 必须明确特征、训练计划、`.fit`、`.predict`、训练证据和预测证据。Hybrid 还必须包含命名的透明信号项。

## Worker 前的窄预检

`agent/validation.py` 只检查 Python 语法，以及 `open`、动态执行、文件、网络、
子进程等明确危险能力。它保留源码与 AST 语义哈希，但不再要求
`initialize_strategy`、特定 helper、特定关键词或轨道形状，也不禁止标准
`set_holdings`/`liquidate`。LEAN 负责 API 和可运行性；独立 Acceptance Agent
结合源码与真实运行证据判断 A2–A4。

## 定向修复与运行证据

Repair 的输入包含当前结构化设计、源码、预检报告、Worker 错误分类、行为证据和 Acceptance failed checks。它必须：

1. 找到第一个中断阶段；
2. 做最小但完整的修复；
3. 输出 `change_summary` 和 `first_interrupted_stage`；
4. 返回完整替换源码。

运行错误目前会归类为 Symbol key、DMatrix API、TradeBars collection API、购买力、Python runtime，以及无模型、无预测、无目标、无订单等零活动阶段。Acceptance 只能依据 Worker 明细判断，不能臆造训练时间、样本数、模型状态或因果链。

2026-07-23 的 Trace 复盘后新增了 `LEAN_SCHEDULE_SIGNATURE` 和 `ALPHAFORGE_EVIDENCE_SIGNATURE` 两类稳定诊断。Repair 必须返回 1–3 条真实修改摘要、一个首个中断阶段和发生实际变化的完整源码；声称修复但返回原样源码会被拒绝。

AlphaForge 证据 API 的固定形式是：

```python
self.af_record_ml_training({
    "model_type": type(self.model).__name__,
    "training_rows": int(len(X_train)),
    "label_horizon_days": int(self.horizon),
    "random_seed": 42,
    "feature_names": list(self.feature_names),
})

self.af_record_ml_prediction({
    "symbol": symbol.value,
    "predicted_alpha": float(prediction),
    "rank": int(rank),
    "selected": bool(symbol in selected_symbols),
})
```

两个函数都不接受多个位置参数或关键字参数。Prediction 必须在最终 Top-K 已经确定后记录，`selected` 必须等于真实目标组合成员资格。

Worker Attempt 持久化完整 Worker 结果和控制台日志。Acceptance 使用关键摘录；
运行失败进入 Repair 时发送完整日志、完整结果、全部失败订单、OrderEvents 和失败前
组合快照。details 缺失仍然 Repair。Acceptance 不再请求在 `on_data` 中加入无限量
debug，而优先要求结构化 `af_record_*` 事件。

DeepSeek 返回空 content 或无效 JSON 时，客户端会自动重试一次，并在重试中关闭 hidden thinking 和 reasoning effort。Trace 会保存每次尝试，便于区分模型偶发错误与策略错误。

对于“设计和 Python 已完整返回，但模型漏掉最外层 JSON 引号或大括号”的情况，客户端会从已知 `design + source_code` 或 Repair 输出协议中恢复完整字段，并在 Trace 中标记 `parse_mode=recovered_known_payload`。只有字段本身不完整时才重新请求；第二次请求会明确要求严格关闭 `source_code` 字符串和外层对象。恢复后的源码仍必须通过 AST 预检，Agent 也不得覆盖基类拥有的 `af_*` 方法。

JSON 能解析但语义 schema 不合法时也会单独重试一次，例如
`design.signals=[]`、字段不是字符串列表、`strategy_spec` 枚举越界或缺少
`source_code`。第二次请求只携带公开上下文和精确校验错误，要求重新返回完整设计与
完整源码。Trace 使用 `semantic_validation_attempts` 保存两次调用；第二次仍失败
才把候选标记为 Failed。

JSON 解析重试与外层语义重试共享同一个两次模型调用预算，因此不会形成
“两次语义尝试 × 每次两次 JSON 尝试”的四次调用。

Repair 对缺少完整源码、无有效 `change_summary`、缺少
`first_interrupted_stage` 或返回未变化源码也执行一次同类语义重试。重试仍严格
限制在同一故障和原有公开上下文内，不借机重写无关策略逻辑。

四个公共基线不再只是附带的四项指标。Designer 会看到其公开的
Sortino、波动、费用、换手、执行完成度和 CAGR/Sharpe/MDD 排名，并必须输出：

- `reference_baselines`：实际参考的 1–2 个公共基线；
- `improvement_hypothesis`：针对公开弱点的可证伪假设；
- `differentiation`：与最近基线至少两个真实设计差异；
- `expected_tradeoff`：可能改善和可能恶化的方面。

这是一种 baseline-informed exploration，而不是要求 Agent 承诺击败基线，更不会
向它泄露 Human 策略或结果。

2026-07-23 的 `forge-396e784b1e3c` 暴露了两项实际退化：Traditional、ML、Hybrid
首次返回都把部分字符串列表压成 scalar，或把 `differentiation` 返回为数组，旧
schema 因此让三条轨道全部多调用一次；Hybrid 的可运行修订曾达到 42.63% CAGR，
但运行证据为 `ml_prediction_count=300`、`ml_training_run_count=0`，说明实际走了
无训练 fallback。后续 Repair 没有解决 History 行数/early-return 根因，最终又
退化成零交易。

对应改进：

- 对可无损转换的 scalar/string-list 形态先归一化，不为格式等价问题重新生成；
- `differentiation` 固定为两个具体变化，生成采用 strong-baseline anchor 和
  minimal-delta challenger，避免一次改模型、期限、Top K、权重和调仓频率；
- ML/Hybrid 必须显式核算 rolling、pct_change、shift、dropna 后的 required bars，
  History 请求数量不得比自己的最小长度判断少一行；
- `PREDICTIONS_WITHOUT_TRAINING` 成为独立因果分类。Repair 必须优先检查训练行数和
  early-return，后续已有 predictions/targets/fills 时不得臆测为 schedule 失效；
- Acceptance Agent 独立输出 A1–A5 和 accept/revise；Backend 只守卫 A1/A5 硬事实与报告一致性；
- 终局 Repair 若退化或调用失败，Backend 保留最佳有交易 Attempt，但仍显示真实
  Rejected 状态。

## 修订是否真的有效

Acceptance 的含义是“可运行、可审计、因果链完整”，不是“收益提高”。因此修复训练行数、时间戳或信号证据时，交易订单和绩效可能完全不变；这种情况现在明确标记为 `evidence_only`，不会再伪装成策略表现提升。

每个 Review 保存源码语义哈希、四项结果、行为证据和已解决检查，并分为：

- `initial_evaluation`：第一次可验收执行；
- `evidence_only`：执行代码和审计证据变化，解决了检查，但交易行为和指标不变；
- `strategy_behavior_change`：交易行为或回测指标发生变化；
- `ineffective`：只有注释/格式变化，或没有解决任何既有失败。

Repair 返回完全相同的源码会直接失败；只有注释和格式变化时，AST 语义哈希不变。
Backend 会把修订有效性和上一轮报告传给 Acceptance Agent，但不会把 A2 改写成
预设结论。Evidence-only 修订仍可能由 Agent 判定解决 A2/A3/A4；PK 胜负另行依据
回测结果决定。

## 五轮 PK 历史

Backend 在独立的 `backend/workspace/run_history/` 中保存最近五次完成的 Forge Run。该目录用于用户界面，不会进入任何 Agent 上下文，也不破坏 Human Strategy 隔离。

每次 Forge Run 是一轮：

- Candidate Selector 先用公开确定性评分选出 accepted AI 内部冠军；
- Battle Judge 再比较 Human 和 AI Champion；
- 评分使用风险调整收益 40%、回撤与波动 25%、稳健性 20%、费用换手 10%、
  可解释性 5%，两分以内为 Draw；
- accepted 只表示 AI 有资格参赛，不表示 AI 获胜；
- 最多保留最近五轮，形成 Best-of-Five 记分板；
- 每轮可以展开三个 AI 候选、每次 Review、修订类型、指标、行为证据和当轮源码。

## 前端工作流

`AI Forge` 页面把一次候选生成拆成五个可见阶段：

1. Public Evidence
2. Independent Design
3. Static Validation
4. LEAN Backtest
5. Acceptance

每个轨道卡片展示设计论点、参考基线、改进假设、差异化设计、预期代价、信号/特征、
静态诊断、生成重试、Worker 状态、修复次数和 token 使用。Results 页面只展示统计与
裁决；最优策略解释、用户建议、指标知识卡和 Baseline Classroom 位于独立 Learning
页面。页面只展示结构化结论，不展示隐藏思维链；信息边界横幅明确说明
`User Strategy Hidden From AI`。

## 验证方法

后端：

```powershell
$env:PYTHONPATH=((Resolve-Path backend).Path + [IO.Path]::PathSeparator + (Resolve-Path .).Path)
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

前端：

```powershell
docker compose run --rm --no-deps frontend npm test -- --run
docker compose build frontend
```

修改提示或预检后，至少确认：

- Traditional、ML、Hybrid 的合法样例通过；
- 已知 `DMatrix`、History subscript、直接调仓绕过被拒绝；
- Trace 中没有 Human 源码或 Human 结果；
- AI Forge 页面能显示设计、预检和修复沿革；
- 新建 Forge Run 真实执行三个候选。

## 尚未完成的边界

这轮是直接生成 Python 架构上的稳定化层，不能数学上保证每个模型响应都成功。文档目标中的完整 CandidateDesign DSL、确定性 DSL→LEAN 编译器、独立 Judge/Critic 和多候选锦标赛仍属于后续阶段。当前最重要的改进是把失败更早、确定性地识别，并让 Repair 围绕真实证据收敛，而不是消耗三次 LEAN 回测重复猜测。
