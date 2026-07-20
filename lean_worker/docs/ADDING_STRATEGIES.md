# 添加传统、ML 或 Hybrid 策略

1. 在 `strategies/approved/<name>/main.py` 添加代码。
2. 继承 `AlphaForgeBaseAlgorithm`，不要直接覆盖 `initialize`、`on_data`、`on_order_event`、`on_end_of_algorithm`。
3. 真实行情已经由 Tiingo 做 adjusted，股票必须使用：

```python
security.set_data_normalization_mode(DataNormalizationMode.RAW)
```

4. 使用结果记录 Hook：

```python
class MyStrategy(AlphaForgeBaseAlgorithm):
    def initialize_strategy(self):
        security = self.add_equity("AAPL", Resolution.DAILY)
        security.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.symbol = self.af_track_symbol(security.symbol)

        spy = self.add_equity("SPY", Resolution.DAILY)
        spy.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.set_benchmark(spy.symbol)
        self.af_set_benchmark_symbol(spy.symbol)

    def on_alpha_data(self, data):
        pass

    def on_alpha_end(self):
        self.debug("MY_COMPLETION_MARKER")
```

5. 在 `strategies/registry/<name>.json` 注册：

```json
{
  "strategy_id": "my_strategy_v1",
  "entry_file": "approved/my_strategy/main.py",
  "algorithm_class": "MyStrategy",
  "expected_marker": "MY_COMPLETION_MARKER",
  "supports_ml": false,
  "requires_real_data": true,
  "required_symbols": ["AAPL", "SPY"],
  "default_parameters": {
    "end_date": "latest"
  }
}
```

6. 重启容器即可，不需要重建镜像，因为 `strategies/` 是只读挂载：

```powershell
.\scripts\restart.ps1
```

ML 记录接口：

```python
self.af_record_ml_training({...})
self.af_record_ml_prediction({...})
self.af_record_model_artifact({...})
self.af_record_signal("signal_name", {...})
```

安全规则：

- 只提交可信策略；
- 不允许网络访问；
- 不允许动态安装依赖；
- 不允许执行系统命令；
- 不允许访问白名单外资产；
- 不允许未来数据；
- 保存策略 SHA256 和全部参数。
