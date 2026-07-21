# Local QC History DataFrame reference

Source: https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/history-responses
Retrieved: 2026-07-20
Applicable profile: LEAN Python, multi-Symbol US Equity TradeBar history, daily resolution

## Response shape

For a Python history request with more than one Symbol, the TradeBar DataFrame uses a row MultiIndex
whose levels are `symbol` followed by `time`. The value columns include `open`, `high`, `low`, `close`,
and `volume`. Timestamps use the exchange time zone. A representative shape is:

```text
                          close    high     low     open      volume
symbol time
SPY    2024-12-17 16:00   ...      ...      ...     ...       ...
       2024-12-18 16:00   ...      ...      ...     ...       ...
QQQ    2024-12-17 16:00   ...      ...      ...     ...       ...
       2024-12-18 16:00   ...      ...      ...     ...       ...
```

Code must validate the returned structure before using it. For this profile, convert one value column
to a time-by-Symbol table by unstacking the `symbol` level, never the `time` level:

```python
history = self.History(list(self.symbols.values()), bar_count, Resolution.Daily)
if history.empty or not isinstance(history.index, pd.MultiIndex):
    return {}
if list(history.index.names[:2]) != ["symbol", "time"]:
    return {}

close = history["close"].unstack(level="symbol").sort_index()
volume = history["volume"].unstack(level="symbol").sort_index()
```

`unstack(level="time")` or `unstack(level=1)` is invalid for this target shape because it produces
timestamps as columns instead of Symbols. Prefer the named level `symbol` over the numeric level `0`.

## Bar-count rules

An n-trading-day close-to-close total return needs n+1 valid closing prices:

```python
def trailing_total_return(close_series: pd.Series, days: int) -> float | None:
    values = close_series.dropna()
    if len(values) < days + 1:
        return None
    window = values.iloc[-(days + 1):]
    return float(window.iloc[-1] / window.iloc[0] - 1.0)
```

Therefore 5/21/63/126-day return features require at least 127 valid closes. A 252-day momentum signal
requires at least 253 valid closes. Do not silently replace a missing value inside the required window
or allow `dropna` to stretch the calendar span without reporting the Symbol as incomplete.

## Availability boundary

The time on a TradeBar is the end of its sampling period and the time at which that bar becomes
available. At a scheduled event after the market opens, daily History must be treated as ending at the
last completed daily bar; the current incomplete daily bar must not be used as a prediction feature.

## Required failure behavior

- Reject an empty response.
- Reject a non-MultiIndex response for a multi-Symbol request.
- Reject unexpected index level names or order.
- Exclude a Symbol that lacks the complete required window.
- Preserve the same accepted Symbol list when constructing feature rows and their DataFrame index.
- Never substitute zeros for missing return, volatility, volume, feature, or label data.
