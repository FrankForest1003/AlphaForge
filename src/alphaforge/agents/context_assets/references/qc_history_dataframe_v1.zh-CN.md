# 本地 QC History DataFrame 参考

来源：https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/history-responses
获取日期：2026-07-20
适用 Profile：LEAN Python、多 Symbol 美股 TradeBar History、日频 Resolution

## 返回结构

对于包含多个 Symbol 的 Python History 请求，TradeBar DataFrame 使用行 MultiIndex，索引层顺序为
`symbol`，然后是 `time`。数值列包括 `open`、`high`、`low`、`close` 和 `volume`。时间戳使用交易所
时区。代表性结构如下：

```text
                          close    high     low     open      volume
symbol time
SPY    2024-12-17 16:00   ...      ...      ...     ...       ...
       2024-12-18 16:00   ...      ...      ...     ...       ...
QQQ    2024-12-17 16:00   ...      ...      ...     ...       ...
       2024-12-18 16:00   ...      ...      ...     ...       ...
```

代码使用返回结果前必须验证其结构。对当前 Profile，应当展开 `symbol` 层，把一个数值列转换成
“时间 × Symbol”表；绝不能展开 `time` 层：

```python
history = self.History(list(self.symbols.values()), bar_count, Resolution.Daily)
if history.empty or not isinstance(history.index, pd.MultiIndex):
    return {}
if list(history.index.names[:2]) != ["symbol", "time"]:
    return {}

close = history["close"].unstack(level="symbol").sort_index()
volume = history["volume"].unstack(level="symbol").sort_index()
```

对该目标结构，`unstack(level="time")` 或 `unstack(level=1)` 是错误的，因为它会生成以时间戳为列、
而不是以 Symbol 为列的表。优先使用具名索引层 `symbol`，不要使用数字索引层 `0`。

## Bar 数量规则

n 个交易日的收盘价到收盘价总收益需要 n+1 个有效收盘价：

```python
def trailing_total_return(close_series: pd.Series, days: int) -> float | None:
    values = close_series.dropna()
    if len(values) < days + 1:
        return None
    window = values.iloc[-(days + 1):]
    return float(window.iloc[-1] / window.iloc[0] - 1.0)
```

因此 5/21/63/126 日收益特征至少需要 127 个有效收盘价。252 日动量至少需要 253 个有效收盘价。
不得静默替换所需窗口中的缺失值，也不得在不报告 Symbol 数据不完整的情况下用 `dropna` 拉长实际
日历跨度。

## 数据可用边界

TradeBar 的时间是该采样周期结束、数据真正可用的时间。在开盘后的 Scheduled Event 中，日频
History 必须被视为截止到上一根完整日线；不得把当日尚未完成的日线作为预测特征。

## 必需的失败行为

- 拒绝空返回。
- 对多 Symbol 请求，拒绝非 MultiIndex 返回。
- 拒绝索引层名称或顺序不符合预期的返回。
- 排除没有完整所需窗口的 Symbol。
- 构造特征行和 DataFrame index 时必须使用同一份已经通过检查的 Symbol 列表。
- 绝不能用零替代缺失的收益、波动率、成交量、特征或标签。
