# price_volume_v1 模型接口

版本：ml_feature_interface_v1
适用范围：qc_semantics_v1 下的 ML 和 Hybrid 路线

## 规范特征列

训练和预测必须使用完全相同的特征顺序和拼写：

```python
FEATURE_COLUMNS = (
    "return_5d",
    "return_21d",
    "return_63d",
    "return_126d",
    "volatility_21d",
    "volatility_63d",
    "volume_ratio_21_63",
)
```

`build_features` 返回以 Symbol 为 index 的 DataFrame，必须严格包含上述列和顺序，并且只包含有限数值
的行。DataFrame index 必须来自实际追加了特征行的同一批 Symbol；不得在过滤后从范围更宽的候选列表
重新构造 index。

`build_training_set` 返回 `(X, y)`。X 是使用 `(time, symbol)` MultiIndex 的 DataFrame，并严格包含
相同的 `FEATURE_COLUMNS`。y 是名为 `label` 的有限数值 Series，index 必须与 X 完全一致。

`fit_model` 必须拒绝空 X/y。它使用 StrategySpec 中的随机种子拟合 estimator。`predict_scores` 必须
拒绝空或包含非有限数值的预测 DataFrame，并向模型传入与训练完全相同、顺序一致的特征列。合法模式：

```python
X = X.loc[:, FEATURE_COLUMNS]
prediction_X = features.loc[:, FEATURE_COLUMNS]
model.fit(X, y)
predictions = model.predict(prediction_X)
```

## 训练日期和标签

- `training_window_days` 统计唯一交易日，不是堆叠后的 Symbol 行，也不是自然日。
- 删除没有完整未来标签的行后，选择最近配置数量的唯一日期。
- 日期 t 的训练特征只能使用截至 t 可用的数据。
- 因为 t 是历史样本，其标签可以使用 t + prediction_horizon_days 的已实现收盘价。
- 当前预测行没有未来标签，绝不能进入 X 或 y。
- 相对 Alpha 回归标签是某 Symbol 的未来收益减去同一 t 下全部有效 Symbol 的未来收益均值。
- 绝不能用零填充缺失特征或标签。

## Hybrid 融合

Traditional 和 ML 分数必须限制在二者共同有效的 Symbol 集合。分别把两组分数转换成横截面百分位，
再使用 StrategySpec 权重融合。如果任一分数向量为空，或者共同 Symbol 少于两个，就不返回分数，并
让确定性的无分数持仓政策执行。
