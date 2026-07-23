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

## Worker 前的确定性预检

`agent/validation.py` 在消耗一次 LEAN 回测前检查：

- `UserStrategy(AlphaForgeBaseAlgorithm)` 和 `initialize_strategy` 是否存在；
- 七项共享设置和 `af_configure_security` 是否完整；
- 是否使用 `af_track_symbol` 和 `af_rebalance_to_weights`；
- 是否存在 `history[TradeBar]`、直接 `set_holdings`、直接 `liquidate`、低层 `DMatrix`；
- import 和危险调用是否超出允许范围；
- Traditional/ML/Hybrid 的轨道完整性；
- ML/Hybrid 是否包含真实训练、预测和证据记录。
- `schedule.on` 是否使用三参数或带名称的四参数重载，拒绝不存在的 `.do(...)` Builder 写法；
- `af_record_ml_training` 与 `af_record_ml_prediction` 是否各自只接收一个字典，并包含完整的标准字段；
- Traditional/Hybrid 是否用 `af_record_signal(name, payload)` 留下透明信号证据；
- 是否把合法的负 `iloc` 尾部索引错误地当成历史不足，从而让信号分支永远不可达；
- 是否对负 shift 产生的不可用未来标签执行 `fillna(0)`。

预检结果包含稳定诊断码、源码 SHA-256 和警告。失败源码不会提交 Worker，而是直接进入 `static_validation` Repair。

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

Worker Attempt 仍持久化完整控制台日志，但发送给 Acceptance 的日志摘录最多 12,000 字符，发送给 Repair 的摘录最多 20,000 字符。摘录保留错误上下文、`main.py` 行号、统计信息、数据使用信息、开头和结尾，避免每日 debug 把 Agent 请求重新推高到 30 万 token。Acceptance 不再请求在 `on_data` 中加入无限量 debug，而优先要求结构化 `af_record_*` 事件。

DeepSeek 返回空 content 或无效 JSON 时，客户端会自动重试一次，并在重试中关闭 hidden thinking 和 reasoning effort。Trace 会保存每次尝试，便于区分模型偶发错误与策略错误。

对于“设计和 Python 已完整返回，但模型漏掉最外层 JSON 引号或大括号”的情况，客户端会从已知 `design + source_code` 或 Repair 输出协议中恢复完整字段，并在 Trace 中标记 `parse_mode=recovered_known_payload`。只有字段本身不完整时才重新请求；第二次请求会明确要求严格关闭 `source_code` 字符串和外层对象。恢复后的源码仍必须通过 AST 预检，Agent 也不得覆盖基类拥有的 `af_*` 方法。

## 修订是否真的有效

Acceptance 的含义是“可运行、可审计、因果链完整”，不是“收益提高”。因此修复训练行数、时间戳或信号证据时，交易订单和绩效可能完全不变；这种情况现在明确标记为 `evidence_only`，不会再伪装成策略表现提升。

每个 Review 保存源码语义哈希、四项结果、行为证据和已解决检查，并分为：

- `initial_evaluation`：第一次可验收执行；
- `evidence_only`：执行代码和审计证据变化，解决了检查，但交易行为和指标不变；
- `strategy_behavior_change`：交易行为或回测指标发生变化；
- `ineffective`：只有注释/格式变化，或没有解决任何既有失败。

Repair 返回完全相同的源码会直接失败；只有注释和格式变化时，AST 语义哈希不变。若模型声称接受一个确定性无效修订，Backend 会把 A2 改回 revise 并要求真正修改。Evidence-only 修订仍允许解决 A2/A3/A4，因为审计能力本身就是这些检查的一部分；PK 胜负另行依据回测结果决定。

## 五轮 PK 历史

Backend 在独立的 `backend/workspace/run_history/` 中保存最近五次完成的 Forge Run。该目录用于用户界面，不会进入任何 Agent 上下文，也不破坏 Human Strategy 隔离。

每次 Forge Run 是一轮：

- Human 对阵该轮 Sharpe 最高的 accepted AI；
- 先比较 Sharpe，再比较 CAGR，最后以更低最大回撤决胜；
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

每个轨道卡片展示设计论点、信号/特征、选择规则、静态诊断、Worker 状态、修复次数、修改摘要和 token 使用。页面只展示结构化结论，不展示隐藏思维链；信息边界横幅明确说明 `User Strategy Hidden From AI`。

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
