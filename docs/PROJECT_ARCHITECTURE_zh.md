# AlphaForge 项目架构

## 产品目标

AlphaForge 是一个面向金融教育的本地策略实验平台。用户在冻结的股票池、
时间区间、初始资金、基准和交易成本下运行 Human 策略，并与四个公共基线
及三条 AI 参数策略比较。系统展示收益、风险、成本、权益曲线、回撤、执行
证据、策略教学和鲁棒性限制。

## 技术栈

- React、Vite、Recharts：交互流程和结果可视化；
- FastAPI、Pydantic：实验编排、API 和结构化契约；
- DeepSeek JSON API：Parameter Designer 与 Performance Critic；
- QuantConnect LEAN：唯一回测执行引擎；
- pandas、NumPy、scikit-learn：固定模板内的数据和模型流水线；
- Docker Compose：Frontend、Backend、LEAN Worker 本地编排。

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
          deterministic best-of-three --------------+
```

## Agent 设计

Designer 只返回完整 `strategy_spec` 和简短教学说明，不返回 Python。
Traditional 必须有透明信号且无模型；ML 必须有模型且无透明信号；Hybrid
必须两者兼有。特征、模型、选股、权重、调仓和风控参数都有明确范围。

Critic 读取公共基线、当前参数、当前表现、执行事实和先前 AI 轮次，输出
诊断、保留项、弱点、最多三项参数调整方向和过拟合提醒。Critic 不输出
替代参数，也不做 accept/reject；下一版完整参数仍由 Designer 负责。

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

每条 AI 赛道最多三次真实回测，最终按 Sharpe、CAGR、较低最大回撤依次
择优。界面保留全部参数、结果和 Critic 建议，让用户观察一次参数变化如何
影响收益、回撤、换手和成本。

三次搜索会引入多重测试偏差，因此“最佳轮次”只代表当前历史样本内的开发
结果。鲁棒性页面继续用时期切片、成本和交易假设压力测试说明结果的敏感性，
不会把回测表现描述为未来收益承诺。

## 信息边界

AI 只能看到冻结设置、公共基线和自己的历史轮次。Human 源码、参数、结果、
订单和个性化教学不会进入 Agent 上下文。Human 自定义代码入口保持独立，
代码的可运行检查和风险提示也不会改变 AI 比赛结果。
