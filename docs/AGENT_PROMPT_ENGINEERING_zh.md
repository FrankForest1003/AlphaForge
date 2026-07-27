# AlphaForge 参数型多 Agent 设计

## 目标与责任边界

AI Agent 不再生成、修复或返回 Python。Agent 只负责投资假设和
`StrategyTemplateSpec` 参数；后端固定模板负责历史数据处理、模型训练、
时间完整性、证据记录、调仓和 LEAN API。

责任边界是：任何通过 `StrategyTemplateSpec` 校验的参数都应能由
`template-v1` 编译并完成 LEAN 回测。合法参数若产生运行异常，应归类为
模板或基础设施缺陷，不允许再交给 Agent 猜测代码修复。

## 两个 Agent

### Parameter Designer

输入仅包括：

- 冻结的实验设置；
- 四个公共基线的核心指标、排名和教学结论；
- 有界策略 DSL；
- 当前赛道；
- 修订轮次中的上轮参数、表现和 Critic 报告。

输出只有：

- `design`：参考基线、可证伪的改进假设、差异和权衡；
- `strategy_spec`：完整模板参数。

提示词不包含 LEAN 文档、Python 模板、Human 策略或 Human 结果。后端用
Pydantic 校验完整对象；修订轮必须至少改变一个规范化参数。

### Performance Critic

Critic 在每次已完成回测后读取参数、公共基线、当前指标、执行事实和先前
AI 轮次。输出诊断、应保留的机制、弱点、最多三项参数调整方向和过拟合
提醒。Critic 不得输出代码、替代参数对象或 accept/reject 决策。

## 三轮优化协议

每条 Traditional、ML、Hybrid 赛道最多执行三次回测：

1. Designer 给出初始参数；
2. 后端校验并编译固定模板；
3. LEAN 回测；
4. Critic 评价结果；
5. Critic 报告交还 Designer，生成下一轮完整参数；
6. 三轮结束后按 Sharpe、CAGR、较低最大回撤依次择优。

这三轮是受限的探索预算，不代表统计显著性，也不会因为第三轮是最新版本
就自动采用第三轮。最终鲁棒性测试仍用于展示策略对时期、成本和交易假设
的敏感性。

## 稳定性机制

- JSON 解析最多重试一次；
- schema 只描述后端真实支持的投资参数；
- `extra="forbid"` 阻止虚构字段；
- 赛道约束确保 Traditional 无模型、ML 无透明信号、Hybrid 两者兼有；
- 总敞口是目标上限；当 Top-K 和单仓上限形成更低容量时，模板保留剩余现金；
- 模板编译确定性地嵌入规范化 JSON 和 SHA-256；
- Agent 不接触 Human 信息，避免比赛信息泄漏；
- 失败分类区分 Agent 参数错误与模板/基础设施缺陷，产品界面只显示稳定错误信息，原始诊断保存在 Trace。
