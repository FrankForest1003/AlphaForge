# AlphaForge 参数化策略模板 v1

## 决策

AI Designer 不再生成 QuantConnect Python。它只返回一个小型、版本化的
`StrategyTemplateSpec` JSON；Backend 校验后，将规范化 JSON 注入固定的
`parameterized_strategy.py.tmpl`，再把生成的完整源码交给 LEAN Worker。

```text
Baseline evidence
      ↓
Designer JSON（约 1–2 KB）
      ↓
Pydantic 结构与跨字段校验
      ↓
固定模板编译器
      ↓
标准生命周期 LEAN Python
      ↓
LEAN + 运行证据 + Acceptance
```

共享股票池、日期、资金、基准、手续费和滑点继续由 `RunSettings` 控制，Agent
无权覆盖。

## 为什么采用一个解释器模板

模板固定处理最容易出错但不需要创意的部分：

- LEAN 生命周期、订阅、参数和调仓日程；
- History 拆分、特征与标签时间对齐；
- 根据特征窗口、标签周期和训练样本量自动计算 History bars；
- sklearn 拟合、预测、Top-K、权重上限和分阶段订单；
- `af_record_signal`、`af_record_ml_training`、
  `af_record_ml_prediction` 证据；
- 市场趋势过滤、止损和组合回撤暂停。

Agent 只负责金融设计选择，因此不会再生成错误 API、错误函数签名、数组长度
不一致或不可能满足的训练行数判断。

## 灵活性边界

### 特征积木

- `return`
- `volatility`
- `sma_gap`
- `relative_return`
- `volume_change`
- `rsi`

每个特征独立选择 `2–252` 日窗口。模型可组合 2–12 个特征；透明信号可组合
1–4 个特征，并为每个特征指定方向与权重。

### 模型积木

- Gradient Boosting
- Random Forest
- Extra Trees
- Ridge

Agent 可选择绝对收益或相对基准的超额收益标签、5–63 日预测周期、80–600 条
池化训练样本、重训间隔和有界超参数。模板统一使用正确的负向 `shift` 构建
前瞻标签，并自动预留特征和标签损失所需的历史长度。

### 决策与组合

- Traditional：透明信号排名；
- ML：模型预测排名；
- Hybrid：模型排名与透明信号排名按可调比例融合；
- Top-K：2–10；
- 权重：等权、逆波动率、得分、最小方差、得分/最小方差混合；
- 周频或月频调仓；
- 总敞口、单股上限、换仓阈值、市场趋势过滤、止损和最大回撤暂停。

因此模板限制的是实现风险，不把策略限制成少数预设成品。

## Hybrid 示例

```json
{
  "schema_version": "template-v1",
  "strategy_name": "ML Relative Strength Risk Blend",
  "track": "Hybrid",
  "thesis": "Model forecasts and medium-term relative strength provide complementary rankings.",
  "signal": {
    "components": [
      {
        "feature": {"kind": "relative_return", "window": 63},
        "direction": "higher",
        "weight": 0.6
      },
      {
        "feature": {"kind": "volatility", "window": 42},
        "direction": "lower",
        "weight": 0.4
      }
    ]
  },
  "model": {
    "algorithm": "gradient_boosting",
    "features": [
      {"kind": "return", "window": 21},
      {"kind": "return", "window": 126},
      {"kind": "volatility", "window": 42},
      {"kind": "relative_return", "window": 63}
    ],
    "target": "excess_return",
    "horizon_days": 21,
    "pooled_training_rows": 360
  },
  "selection": {
    "top_k": 5,
    "hybrid_model_weight": 0.55
  },
  "portfolio": {
    "weighting": "blend_score_minimum_variance",
    "gross_exposure": 0.9,
    "max_position_weight": 0.25,
    "minimum_variance_blend": 0.35
  },
  "schedule": {"frequency": "monthly"},
  "risk": {
    "market_trend_filter": true,
    "market_sma_window": 200
  }
}
```

## 当前范围

本阶段只落地模板契约、确定性编译器和静态测试。现有 Designer/Repair Prompt
及 Forge 编排尚未切换到参数模式。下一阶段应让 Designer 只接收：

1. 精简的公共基线摘要；
2. 上述 DSL 的紧凑字段表；
3. 所属轨道和运行设置；
4. 一条“仅返回 JSON、不得返回代码”的明确要求。

Repair 也应改为修订 JSON 参数，而不是修订 Python。

## 端到端 LEAN 验证

2026-07-24 使用相同的八只股票、2020-01-02 至 2021-12-31、10 bps 手续费和
5 bps 滑点，将 `examples/strategy_specs/` 的三份纯 JSON 分别经过编译器后
提交给真实 LEAN Worker。三次运行均为 `completed`、无引擎错误、无失败的
分阶段调仓：

| 轨道 | Run ID | 透明信号 | ML 训练 | ML 预测 | Signal→Target | Prediction→Target | Hybrid 同刻链路 |
|---|---|---:|---:|---:|---:|---:|---:|
| Traditional | `20260724-074300-62b7d7ea` | 24 | 0 | 0 | 24 | 0 | 0 |
| ML | `20260724-074300-0d4cecd2` | 0 | 24 | 192 | 0 | 24 | 0 |
| Hybrid | `20260724-074300-c0c6e3f4` | 24 | 9 | 192 | 24 | 24 | 24 |

每条轨道均完成 24 次 staged rebalance，`staged_rebalance_failed_count = 0`。
这组结果验证的是模板表达能力、转换器和因果证据分离，不构成未来收益保证。
