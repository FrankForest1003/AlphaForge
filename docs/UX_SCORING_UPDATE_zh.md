# AlphaForge 用户体验与评估更新

## 本次范围

- LEAN Worker Pool 扩展为 4 个隔离槽位，四个公共基线可同时提交。
- Human Guided Mode 保留基础模板，并新增多因子进阶模板。
- 确定性评分和鲁棒性协议升级。
- Learning Review 增加异步教学解释和可视化。

## Human 策略

基础和进阶 Guided Mode 都会先转换成合法的 `StrategyTemplateSpec`，然后通过
固定的 `template-v1` 编译，不由 LLM 编写 Python。进阶模式允许选择动量、
均值回归、低波动、动量与低波动组合、相对趋势质量，并调整：

- 主次因子窗口和因子权重；
- 持仓数量、等权/逆波动/信号分数加权；
- 总敞口、单股上限和免交易阈值；
- 正信号约束、市场趋势过滤和均线窗口。

完整 QuantConnect Python 输入仍然保留，并继续使用原有代码检查与 LEAN 回测。

## 评分 v2

所有合格策略按同一组确定性权重比较：

- Sharpe Ratio：35%
- CAGR：30%
- 最大回撤控制：15%
- 波动率控制：5%
- 成本效率：5%
- 执行证据：5%
- 可解释性：5%

Sharpe 与 CAGR 合计占 65%，因此一个同时具有更高 Sharpe 和 CAGR 的策略不会
轻易被次要展示项反超。鲁棒性实验尚未运行时，评分项明确称为“执行证据”，不再
把有订单、有持仓误称为鲁棒性。

## 鲁棒性协议 v2

Recent regime、delayed start、double friction 和 universe dropout 使用不同的
CAGR 保留率、Sharpe 保留率和最大回撤阈值。总分按照场景重要度加权，同时加入：

- 每个计划场景必须完成；
- 策略必须保持真实成交和持仓；
- 最差场景分数约束；
- 明确区分敏感性测试和真正的样本外验证。

任何场景未完成时只返回 `insufficient`，不会给出虚假的 robust 结论。

## Teaching Explainer

Forge 的确定性结果先完成，Teaching Explainer 随后异步生成教学内容。它只能读取
已冻结的冠军、评分、参数、三轮迭代、Critic 和鲁棒性证据，不能修改冠军或分数。
输出包括：

- 最优策略的信号到持仓解释；
- 有证据支持的领先原因和失效场景；
- 每次只改变一个合法参数的下一轮实验；
- 与本轮问题相关的 Quant Concept；
- 针对本轮搜索过程的过拟合提醒。

模型失败不会导致 Forge Run 失败；界面会自动使用确定性教学内容。

## Learning Review 可视化

- Strategy DNA：数据、决策、选股、配置和风控链路；
- Risk–Return Map：横轴最大回撤、纵轴 Sharpe、气泡大小表示 CAGR；
- Three-Trial Evidence：三次 AI 回测及最终保留轮次；
- Next-Round Lab：参数当前值、建议值、目标指标、副作用和验证方法。
