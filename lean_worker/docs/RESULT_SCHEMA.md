# result.json schema 2.0

- `run`：run ID、状态、创建时间。
- `strategy`：策略类、参数、源码 SHA256、完成标志。
- `environment`：Runtime、LEAN commit、Python 和 ML 包版本。
- `dataset`：数据版本、来源、共同结束日期、质量摘要和 Catalog SHA256。
- `engine`：退出码、LEAN 分析完成、Python shutdown、clean shutdown。
- `summary`：前端 KPI 卡片。
- `statistics`：LEAN 统计全集。
- `performance.equity_curve`：净值、现金、持仓市值。
- `performance.drawdown_curve`：由净值曲线计算。
- `performance.benchmark_curve`：SPY 价格、归一化值和收益。
- `performance.cash_curve`：现金曲线。
- `performance.exposure_curve`：Gross/Net exposure。
- `portfolio.position_snapshots`：每日、成交后、最终持仓。
- `portfolio.final_positions`：最终持仓。
- `execution.orders`：订单最终状态。
- `execution.order_events`：全部订单事件。
- `execution.fills`：实际成交事件。
- `execution.closed_trades`：根据成交 FIFO 重构的闭合交易。
- `signals`：传统/ML 策略评分、排名、选择和目标权重。
- `ml.training_runs`：模型、训练窗口、样本数和特征重要性。
- `ml.predictions`：每次训练后的全部股票预测、排名和目标权重。
- `ml.model_artifacts`：模型文件及 SHA256。
- `data_quality`：LEAN 实际数据请求统计。
- `evaluation`：能否进入 Agent 比较及拒绝原因。
- `diagnostics`：错误、警告和原始统计。
- `artifacts`：本地结果、日志、config、manifest 和模型目录。

完整结果保存在：

```text
workspace/results/<run_id>/result.json
```
