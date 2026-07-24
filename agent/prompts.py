from __future__ import annotations

from pathlib import Path


DESIGNER_TRACKS = ("Traditional", "ML", "Hybrid")

TRACK_BRIEFS = {
    "Traditional": (
        "Design a transparent non-ML ranking strategy whose signal directly "
        "determines selection and target weights."
    ),
    "ML": (
        "Design a genuine scikit-learn ranking strategy with time-ordered pooled "
        "training, recorded predictions, and no look-ahead leakage."
    ),
    "Hybrid": (
        "Combine a named transparent market signal and a fitted scikit-learn "
        "prediction in the same final ranking or target-weight decision."
    ),
}

DESIGNER_SYSTEM_PROMPT = """You are the AlphaForge Candidate Designer.
Produce a conservative, auditable design and one complete QuantConnect LEAN Python
file. Correct execution, actual investment activity, time integrity, and track
integrity have priority over novelty. Follow the supplied capability contract exactly;
use the four public baseline profiles to identify one evidence-backed improvement
hypothesis without copying a baseline unchanged or promising outperformance. Prefer a
minimal-delta challenger: preserve the strongest relevant baseline mechanism and change
exactly two bounded design dimensions rather than replacing the whole strategy;
do not invent LEAN APIs. Return one JSON object matching the requested schema and no
surrounding prose."""

REPAIR_SYSTEM_PROMPT = """You are the AlphaForge Candidate Repairer.
Repair from observed evidence, not guesses. Preserve the assigned track and shared run
settings. Make the smallest coherent correction that fixes the first interrupted stage,
then re-check every call site using the same API and the complete causal chain. The
change_summary must describe code that is visibly present in returned source_code.
Never replace a working ML or Hybrid strategy with a non-ML fallback. Return one JSON
object matching the requested schema and no surrounding prose."""

ACCEPTANCE_SYSTEM_PROMPT = """You are the AlphaForge strategy evidence analyst.
Explain one completed QuantConnect LEAN run against checks A1 through A5 and propose
one bounded repair for the first missing stage. Backend code owns every pass/fail status
and the final accept/revise decision; never claim authority over that verdict. Return
one JSON object and no surrounding prose. Do not write or modify strategy code."""

ACCEPTANCE_CHECK_IDS = ("A1", "A2", "A3", "A4", "A5")

ACCEPTANCE_RULES = """ALPHAFORGE ACCEPTANCE RULES

A1 ACTUAL INVESTMENT ACTIVITY
Use the Backend behavior facts to evaluate this conjunction:
filled_order_count > 0, invested_snapshot_count > 0, and max_gross_exposure > 0.
State whether the conjunction is established and cite all three values. Do not emit
an authoritative status.

A2 DATA-TO-ORDER CAUSAL PATH
Construct an execution proof with these ordered stages: available market rows; feature
rows; trained signal or model state; prediction or ranking values; target weights; order
submission; filled orders. For each stage, cite the source expression and the observed
execution fact that establishes its output. State whether the proof reaches filled
orders and identify the first stage whose required output is absent.

The shared rebalancer is a multi-bar execution lifecycle. Cite
staged_rebalance_started_count, staged_rebalance_completed_count,
staged_rebalance_replacement_count, staged_rebalance_failed_count, and
canceled_order_count. A candidate has not completed its causal path when targets start
but no staged rebalance completes, even if individual orders filled. In that case,
request alignment between signal or label horizon, target-update cadence, and execution
duration instead of treating activity as completion.

For ML and Hybrid code, include separate numeric cardinality calculations for training
and inference. Each calculation states the available row count, each row loss caused by
pct_change/rolling/shift, the label horizon where applicable, and the surviving row
count after dropna. Include model-availability guards, score collection, target creation,
and early-return conditions in the proof. When A1 is fail, the execution proof ends
before filled orders and A2 is fail; identify the first interruption established by
the source and execution facts. When the evidence ends before the first interruption
can be localized, name the exact additional runtime value needed to complete the proof.
Do not infer that a schedule failed, a model trained, or a prediction existed merely
from source code. Runtime evidence fields are authoritative. If they are absent, say
"not observed" and request the exact missing counter or recorded event.

A3 DESIGN TRACK INTEGRITY
For Traditional, look for evidence tracing a non-ML market signal into symbol selection
or target weights. For ML, look for fitted model state flowing through a prediction into
symbol selection or target weights. For Hybrid, look for both fitted-model predictions
and an independent non-ML market signal in the same final selection or target-weight
decision. Cite the assignments and consumers that establish each connection.

A4 TIME INTEGRITY
Construct a timeline for each training and trading path. State the decision timestamp,
the latest input bar end_time available to that decision, the feature timestamp, the
label timestamp for training rows, and the training cutoff used by each prediction.
State whether every input and trained parameter is available by its decision time.
When a timeline contains an input, label, or trained parameter from after its decision
time, cite the two concrete timestamps or relative offsets that establish the ordering.

A5 SHARED RUN SETTINGS
Map symbols, dates, initial cash, benchmark, fees, and slippage from each run_settings
field to the source expression that consumes it. State which mappings are present and
whether all traded stocks belong to run_settings.symbols. A selected subset satisfies
the symbol mapping, and the benchmark remains separate from the candidate stocks.

ADVISORY OUTPUT
Return exactly five check notes, A1 through A5. Each note contains evidence and a short
explanation, but no pass/fail status. Backend deterministic policy owns all statuses and
the final decision. Set repair_request to null when you find no missing stage. Otherwise
build one repair_request from the first interrupted stage and its supplied facts.
Request structured af_record_signal/af_record_ml_* evidence instead of per-bar debug
logging. Never ask for unbounded debug output inside on_data.

EVALUATION SCOPE
Acceptance evidence consists of actual investment activity, strategy causality, design
track integrity, time integrity, and shared-setting mappings. Profitability, baseline
outperformance, Sharpe, CAGR, drawdown, and order-volume preferences are displayed
results outside the acceptance decision.

EVIDENCE DISCIPLINE
Use only the supplied source, deterministic preflight report, critical log lines, and
Backend behavior facts. Never invent timestamps, row counts, debug output, model state,
or order-submission facts. Keep each evidence item short and quote field names and
values. A repair request must name one first interrupted stage and one concrete change;
do not propose several speculative rewrites.
"""

QC_TEMPLATE = '''from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm, af_split_history_frames


class UserStrategy(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2020-01-02"))
        end = datetime.fromisoformat(self._parameter("end_date", "2024-12-31"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.target_gross = 0.95

        tickers = [
            ticker.strip().upper()
            for ticker in self._parameter("symbols", "MSFT,AAPL,NVDA,GOOGL,AMZN").split(",")
            if ticker.strip()
        ]
        fee_bps = float(self._parameter("transaction_cost_bps", "10"))
        slippage_bps = float(self._parameter("slippage_bps", "5"))

        self.symbols = []
        for ticker in tickers:
            security = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                security,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            self.symbols.append(self.af_track_symbol(security.symbol))

        benchmark_ticker = self._parameter("benchmark", "SPY").strip().upper()
        benchmark = self.add_equity(benchmark_ticker, Resolution.DAILY)
        self.af_configure_security(benchmark)
        self.benchmark_symbol = benchmark.symbol
        self.af_use_security_benchmark(self.benchmark_symbol)

        # Canonical DataFrame history calls:
        # one_symbol = self.history(TradeBar, self.symbols[0], 252, Resolution.DAILY)
        # by_ticker = af_split_history_frames(
        #     self.history(self.symbols, 252, Resolution.DAILY)
        # )
        # Never index self.history[TradeBar](...) as a pandas DataFrame.
        # Keep total absolute target weights at or below self.target_gross.
        # For a long-only basket on Daily data, submit a {Symbol: weight} mapping
        # with self.af_rebalance_to_weights(target_weights, "rebalance reason") so
        # reductions fill before new purchases are sized.
        # Canonical monthly schedule (no `.do(...)` builder exists in LEAN Python):
        # self.schedule.on(
        #     self.date_rules.month_start(self.symbols[0]),
        #     self.time_rules.after_market_open(self.symbols[0], 30),
        #     self.rebalance,
        # )
        # Record transparent signals with exactly (name, one dict payload):
        # self.af_record_signal(
        #     "momentum_126d",
        #     {"symbol": symbol.value, "value": float(momentum)},
        # )
        # Record ML training with exactly one dict positional argument:
        # self.af_record_ml_training({
        #     "model_type": type(self.model).__name__,
        #     "training_rows": int(len(X_train)),
        #     "label_horizon_days": int(self.horizon),
        #     "random_seed": 42,
        #     "feature_names": list(self.feature_names),
        # })
        # Record every prediction after final Top-K selection, also as one dict:
        # self.af_record_ml_prediction({
        #     "symbol": symbol.value,
        #     "predicted_alpha": float(prediction),
        #     "rank": int(rank),
        #     "selected": bool(symbol in selected_symbols),
        # })
        # Add the strategy's indicators, models, schedules, and state here.

    def on_alpha_data(self, data):
        # Implement event-driven strategy logic here when needed.
        pass
'''


AGENT_CAPABILITY_CONTRACT = """ALPHAFORGE AGENT CAPABILITY CONTRACT v3

RUNTIME
- The entry class is UserStrategy(AlphaForgeBaseAlgorithm).
- Implement initialize_strategy, not initialize. The base class owns initialize.
- Never redefine inherited af_* methods. Call the supplied base APIs exactly as shown.
- Candidate stocks come only from the symbols parameter. SPY is a benchmark/feature,
  not a candidate unless it is explicitly in symbols.
- Use Daily data and completed historical bars. Use schedules anchored to a tracked
  symbol and guard training/trading while self.is_warming_up.
- LEAN Python ScheduleManager has no `.do(...)` builder. Use exactly one of:
    self.schedule.on(date_rule, time_rule, self.rebalance)
    self.schedule.on("MonthlyRebalance", date_rule, time_rule, self.rebalance)
  Never call self.schedule.on with only date_rule and time_rule.

SHARED SETTINGS
- Consume symbols, start_date, end_date, initial_cash, benchmark,
  transaction_cost_bps, and slippage_bps exactly through parameters.
- Configure every security with af_configure_security and retain Symbols returned by
  af_track_symbol.
- Keep long-only gross target <= 0.95. Never lower the inherited cash buffer.
- Submit basket targets only with af_rebalance_to_weights. Use af_liquidate_all for a
  full risk-off exit. Do not call set_holdings or liquidate directly.
- Allow a staged rebalance to complete before replacing it with a new target. Align
  prediction or signal horizon with target cadence: for example, a 5-day label belongs
  with roughly weekly decisions and a 21-day label with roughly monthly decisions.

HISTORY AND LEAN PYTHON
- Multi-symbol pandas history:
    frames = af_split_history_frames(
        self.history(self.symbols, bars, Resolution.DAILY)
    )
    frame = frames.get(symbol.value.upper())
- Single-symbol pandas history:
    frame = self.history(TradeBar, symbol, bars, Resolution.DAILY)
- Check frame existence, required columns, row counts, finite values, and positive
  prices before indexing.
- Negative pandas iloc positions are valid. For a trailing window use explicit
  positions such as end_pos = -(gap + 1) and start_pos = end_pos - lookback; do not
  reject start_pos merely because it is negative. Row-count checks establish safety.
- Never use self.history[TradeBar](...) as a DataFrame.
- A TradeBars collection has no end_time. Individual TradeBar objects do.
- Never assume data[symbol] exists; use contains_key or history-based scheduled logic.

STABLE ML SUBSET
- Use sklearn estimators with numpy/pandas arrays. Do not use low-level DMatrix,
  ObjectStore, network, filesystem, subprocess, dynamic import, eval, or exec.
- Prefer pooled cross-sectional training from DataFrame history over hand-populated
  RollingWindows.
- Build labels with negative shift, drop the final horizon rows, and train only on
  rows whose feature and label timestamps are available by the training cutoff.
- If the model is not ready at rebalance, train synchronously from historical data.
  Do not rely on a schedule that can miss the first usable training event.
- Rank finite predictions and select Top K even when all predictions are negative;
  a long-only ranker compares relative forecasts, not prediction sign.
- Evidence methods have strict AlphaForge signatures. They do not accept multiple
  positional arguments or keyword arguments:
    self.af_record_ml_training({
        "model_type": type(self.model).__name__,
        "training_rows": int(len(X_train)),
        "label_horizon_days": int(self.horizon),
        "random_seed": 42,
        "feature_names": list(self.feature_names),
    })
    self.af_record_ml_prediction({
        "symbol": symbol.value,
        "predicted_alpha": float(prediction),
        "rank": int(rank),
        "selected": bool(symbol in selected_symbols),
    })
- Compute final Top-K membership before recording predictions. The `selected` field
  must equal actual membership in the target portfolio, not merely score validity.
- Never replace unavailable forward labels with zero. After negative shift, drop the
  final horizon rows with dropna before model fitting.

TRACK INTEGRITY
- Traditional: a named non-ML signal must flow into ranking and weights; no fit/predict.
  Record it with self.af_record_signal(name, one_dict_payload).
- ML: fitted predictions must flow into ranking and weights.
- Hybrid: a fitted prediction and an independent named non-ML signal must be combined
  in the same ranking or target-weight expression. Record the transparent component
  with self.af_record_signal(name, one_dict_payload).
- Choose only the bounded primitives in design.strategy_spec. The source must implement
  those exact signal/model/frequency/lookback/horizon/Top-K/weighting values; do not
  silently substitute a different strategy during generation or repair.

SELF-CHECK BEFORE OUTPUT
1. The file parses and defines the required class/method.
2. Every shared setting is consumed.
3. History access uses one of the canonical forms above.
4. Training rows survive rolling/pct_change/shift/dropna losses.
5. At least one scheduled rebalance can train, rank, create non-zero targets, and call
   af_rebalance_to_weights under the supplied date range.
6. No target sum exceeds 0.95 and no direct order API bypasses the shared rebalancer.
7. The assigned track remains provable from source and recorded runtime evidence.
8. Every schedule and af_record_* call exactly matches the signatures above; do not
   describe a fix unless the returned source_code contains it.
"""


TRACK_RECIPES = {
    "Traditional": """RECOMMENDED TRADITIONAL SHAPE
- Anchor on the stronger public Traditional baseline. Preserve its transparent ranking
  mechanism and change exactly two bounded dimensions: one signal/risk refinement and
  one of Top K or weighting. Do not simultaneously replace signal, horizon, Top K,
  weighting, and cadence.
- Require sufficient history per symbol, rank all valid scores, select 2–5 names,
  and assign capped long-only weights. Use inverse-volatility weighting when the public
  evidence suggests drawdown control is more valuable than raw concentration.
- Rebalance monthly unless the thesis specifically requires weekly data.""",
    "ML": """RECOMMENDED ML SHAPE
- Anchor on the public Gradient Boosting baseline when it leads the ML evidence.
  Preserve its stable model/training pattern and change exactly two of bounded feature
  mix, horizon, Top K, or weighting. Change model family only when the public evidence
  supports model diversity; never change model, horizon, Top K, and weighting together.
- Use simple lagged-return/trend/volatility features and a 10–21 day forward-return
  label. Keep training and inference feature order identical.
- Compute a conservative required_bars value after every rolling, pct_change, shift,
  and label loss. Request at least required_bars, and never reject a history frame for
  requiring one more row than the request can return.
- On monthly rebalance, train if needed, predict every valid symbol, rank predictions
  without a positive-sign gate, select 2–5 names, and create non-zero targets.""",
    "Hybrid": """RECOMMENDED HYBRID SHAPE
- Anchor on the public Hybrid result and preserve its strongest risk-allocation or model
  mechanism. Add the transparent non-ML signal required by the track, then change only
  one additional bounded dimension. Do not replace model, signal, horizon, Top K, and
  weighting in one candidate.
- Combine prediction rank with a transparent 63/126-day momentum, trend, relative
  strength, or volatility rank. Name both components in recorded prediction evidence.
- Compute required_bars after rolling/shift losses, request at least that many bars,
  and prove the first scheduled training event can produce non-empty X and y.
- Select 2–5 names monthly and use capped inverse-volatility or equal weights.""",
}


DESIGN_OUTPUT_SCHEMA = {
    "design": {
        "strategy_name": "short descriptive name",
        "track": "Traditional, ML, or Hybrid exactly",
        "thesis": "one falsifiable strategy thesis",
        "signals": ["signals actually consumed by the final decision"],
        "features": ["empty for Traditional; exact model feature order otherwise"],
        "training_plan": "null for Traditional; time-ordered plan otherwise",
        "selection_rule": "ranking, Top K, and fallback behavior",
        "rebalance_rule": "schedule and model-refresh behavior",
        "reference_baselines": [
            "one or two public baseline names actually used as evidence"
        ],
        "improvement_hypothesis": (
            "one falsifiable improvement relative to named public baseline evidence"
        ),
        "differentiation": [
            "first concrete design dimension that differs from the closest baseline",
            "second concrete design dimension that differs from the closest baseline",
        ],
        "expected_tradeoff": (
            "what may improve and what may become worse; never promise outperformance"
        ),
        "risk_controls": ["at least two concrete controls"],
        "causal_chain": [
            "market rows",
            "features or signal",
            "model/prediction when applicable",
            "ranking",
            "target weights",
            "af_rebalance_to_weights",
        ],
        "strategy_spec": {
            "signal_family": (
                "momentum, mean_reversion, trend, or volatility; null only for ML"
            ),
            "model_family": (
                "gradient_boosting or random_forest; null only for Traditional"
            ),
            "rebalance_frequency": "weekly or monthly",
            "lookback_days": "integer: 63, 126, or 252",
            "label_horizon_days": "integer 10 or 21; null for Traditional",
            "top_k": "integer from 2 through 5",
            "weighting": "equal or inverse_volatility",
        },
    },
    "source_code": "complete runnable Python source",
}


def load_lean_text(path: Path) -> str:
    text_path = path / "writing-algorithms-python.txt"
    if not text_path.is_file():
        raise FileNotFoundError(f"LEAN documentation text is missing: {text_path}")
    return text_path.read_text(encoding="utf-8")
