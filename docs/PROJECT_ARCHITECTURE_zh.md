# AlphaForge 项目架构

## 产品目标

AlphaForge 是一个面向金融教育的本地策略实验平台。用户在冻结的股票池、
时间区间、初始资金、基准和交易成本下运行 Human 策略，并与四个公共基线
及三条 AI 参数策略比较。系统展示收益、风险、成本、权益曲线、回撤、执行
证据、策略教学和鲁棒性限制。

## 技术栈

- React、Vite、Recharts：交互流程和结果可视化；
- FastAPI、Pydantic：实验编排、API 和结构化契约；
- DeepSeek JSON API：Parameter Designer、Performance Critic、跨轮 AI Coach 与 Teaching Explainer；
- QuantConnect LEAN：唯一回测执行引擎；
- pandas、NumPy、scikit-learn：固定模板内的数据和模型流水线；
- SQLite：用户、会话、五局三胜对战、轮次结果和 Coach 记忆持久化；
- Docker Compose：Frontend、Backend 和四个隔离的 LEAN Worker 槽位本地编排。
- Worker Pool：按当前负载把任务固定路由到一个 Worker；共享只读行情数据，但隔离配置、锁、任务、模型和结果目录。

## 系统流程

```text
ExperimentContract
        |
        +--> 4 public baselines --------------------+
        |                                           |
        +--> Human guided/custom code --> LEAN -----+--> Results/Education
        |                                           |
        +--> 3 Parameter Designers                  |
               | StrategyTemplateSpec               |
               v                                    |
          Schema validation                         |
               |                                    |
          template-v1 compiler                      |
               |                                    |
          LEAN trial 1 --> Critic --> Designer      |
          LEAN trial 2 --> Critic --> Designer      |
          LEAN trial 3 --> Critic                    |
               |                                    |
          deterministic best-of-three               |
               |                                    |
          compare track incumbent ------------------+
               |
          AI Coach: refine / rotate / rebuild
```

## Agent 设计

Designer 只返回完整 `strategy_spec` 和简短教学说明，不返回 Python。
Traditional 必须有透明信号且无模型；ML 必须有模型且无透明信号；Hybrid
必须两者兼有。特征、模型、选股、权重、调仓和风控参数都有明确范围。

Critic 读取公共基线、当前参数、当前表现、执行事实和先前 AI 轮次，输出
诊断、保留项、弱点、最多三项参数调整方向和过拟合提醒。Critic 不输出
替代参数，也不做 accept/reject；下一版完整参数仍由 Designer 负责。

AI Coach 在每轮结束后读取公开基线和三条 AI 赛道证据，不读取 Human
信息。后端先确定性计算试验改善、历史冠军是否被保留以及相对最强基线的
差距；Coach 再为每条赛道选择继续微调、更换核心机制或重建方案。该指令
会进入下一轮 Designer 上下文，并带有变更范围和参数修改预算。

## 可运行性保证

`StrategyTemplateSpec` 是 Agent 和模板的共同契约。后端先用 Pydantic
规范化参数，再将规范化 JSON 注入 `parameterized_strategy.py.tmpl`。
模板统一实现：

- 参数化股票、日期、资金、基准、费用和滑点；
- 完成历史 bar 的特征计算；
- 无前视的 pooled training 和 forward label；
- Traditional/ML/Hybrid 三种因果路径；
- Top-K、五种权重方式、趋势过滤、止损和回撤冷却；
- AlphaForge 训练、预测、信号、目标和成交证据。

编译产物包含规范 SHA-256，可从历史轮次复现。合法参数仍发生运行异常时，
错误归属模板或基础设施，而不是再让 Agent 修改代码。

## 三轮择优与教育意义

每条 AI 赛道每轮最多三次真实回测，最终按 Sharpe、CAGR、较低最大回撤
依次择优。同一场对战还会把本轮最优与该赛道跨轮冠军比较；未能超越时保留
旧冠军的参数、代码、指标和真正的冠军迭代谱系。本轮挑战记录仍单独保留，
不会被错误展示为冠军进化过程。

三次搜索会引入多重测试偏差，因此“最佳轮次”只代表当前历史样本内的开发
结果。鲁棒性页面继续用时期切片、成本和交易假设压力测试说明结果的敏感性，
不会把回测表现描述为未来收益承诺。

## 信息边界

AI 只能看到冻结设置、公共基线和自己的历史轮次。Human 源码、参数、结果、
订单和个性化教学不会进入 Agent 上下文。Human 自定义代码入口保持独立，
代码的可运行检查和风险提示也不会改变 AI 比赛结果。

## 对战与持久化

用户登录、会话、对战合同、最多五轮结果、教学建议和 Coach 记忆保存在
SQLite。第一轮冻结市场与回测设置，并保存四个基线的完整证据；后续轮次
直接复用第一轮基线。完成的 Forge 页面快照同时保存在 run history，后端
重启后可恢复历史 Run、策略代码、曲线和冠军谱系。前端提供 R1–R5 切换、
整场对战删除和下一轮 Human 参数预填。
