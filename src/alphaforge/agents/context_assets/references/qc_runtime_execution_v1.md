# Local QC runtime execution reference

Sources:
- https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/warm-up-periods
- https://www.quantconnect.com/docs/v2/writing-algorithms/scheduled-events
- https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/position-sizing
Retrieved: 2026-07-20
Applicable profile: LEAN Python, daily US Equities, monthly long-only rebalance

## Warm-up

LEAN replays historical data during warm-up and does not permit trading in that period. Every order
path must return while `self.IsWarmingUp` is true. Requested warm-up counts are not a guarantee that
each Symbol has that many valid observations: illiquidity, IPO dates, missing data, and market hours
can reduce the available rows. Code must still check data completeness at rebalance time.

```python
if self.IsWarmingUp:
    return
```

Warm-up readiness does not replace feature, label, or estimator readiness checks.

## Monthly schedule

When a Symbol is supplied to `DateRules.MonthStart`, the event is tied to that Symbol's first trading
day of the month rather than the first calendar day. `TimeRules.AfterMarketOpen(anchor, 30)` schedules
the callback 30 minutes after that Symbol's market open.

```python
self.Schedule.On(
    self.DateRules.MonthStart(anchor),
    self.TimeRules.AfterMarketOpen(anchor, 30),
    self.Rebalance,
)
```

Register this schedule exactly once in `Initialize`. A separate same-date guard is still required to
prevent duplicate execution if another callback path invokes rebalance.

## Position targets

`SetHoldings(symbol, weight)` calculates an order quantity from the requested portfolio weight and
submits a market order. Existing positions may need to be reduced before new positions are increased.
For the current small long-only basket, the deterministic skeleton must first liquidate non-selected
holdings and then apply the capped target weights.

The target portfolio invariants are:

```text
selected_count <= top_k
each target >= 0
each target <= max_position_weight
sum(targets) <= max_leverage
non-selected invested Symbols are liquidated
```

If score construction fails or returns no valid Symbols, the strategy must follow an explicit policy.
For AlphaForge v1 the safe policy is to liquidate existing holdings rather than retain stale exposure.
This behavior belongs to the deterministic skeleton, not an Agent-generated region.
