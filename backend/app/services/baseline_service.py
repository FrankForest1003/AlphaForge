from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent import DESIGNER_TRACKS
from app.schemas import (
    GuidedHumanStrategy,
    HumanStrategyRequest,
    RunSettings,
    compact_iteration_result,
)
from app.services.strategy_template import (
    TEMPLATE_VERSION,
    compile_strategy_source,
    validate_strategy_spec,
)
from app.services.worker_client import LeanWorkerClient, WorkerClientError


BASELINES = (
    {
        "strategy_id": "classic_30_stock_top3_momentum_v1",
        "name": "Momentum Rank",
        "family": "Traditional",
    },
    {
        "strategy_id": "classic_30_stock_mean_reversion_v1",
        "name": "Mean Reversion",
        "family": "Traditional",
    },
    {
        "strategy_id": "ml_30_stock_gradient_boosting_v1",
        "name": "Gradient Boosting",
        "family": "Machine Learning",
    },
    {
        "strategy_id": "hybrid_30_stock_ml_momentum_min_variance_v1",
        "name": "Hybrid ML + Minimum Variance",
        "family": "Hybrid",
    },
)

TERMINAL_STATES = {"completed", "completed_with_data_gaps", "failed", "timeout"}
MAX_TEMPLATE_BACKTESTS = 3
MAX_MATCH_ROUNDS = 5
MAX_PUBLIC_CURVE_POINTS = 520

PUBLIC_AI_PARAMETER_ERROR = (
    "The AI proposal did not meet the strategy parameter contract after its "
    "validation retry. Technical details are available in the run trace."
)
PUBLIC_AI_GENERATION_ERROR = (
    "The AI proposal could not be completed. Technical details are available "
    "in the run trace."
)
PUBLIC_BACKTEST_SERVICE_ERROR = (
    "The backtest service could not complete this candidate. Technical details "
    "are available in the run trace."
)
PUBLIC_TEMPLATE_RUNTIME_ERROR = (
    "The compiled strategy did not complete its LEAN backtest. Technical details "
    "are available in the run trace."
)
PUBLIC_FORGE_RUN_ERROR = (
    "The Forge run stopped because an internal step could not be completed. "
    "Technical details are available in the run trace."
)


def public_agent_failure(trace: dict[str, Any] | None) -> tuple[str, str]:
    """Return a stable public code/message while raw provider details stay in Trace."""

    semantic_attempts = (trace or {}).get("semantic_validation_attempts") or []
    if any(item.get("status") == "schema_failed" for item in semantic_attempts):
        return "agent_parameter_schema", PUBLIC_AI_PARAMETER_ERROR
    return "agent_generation_failed", PUBLIC_AI_GENERATION_ERROR


BASELINE_LESSONS = {
    "Momentum Rank": {
        "principle": "Ranks stocks by medium-term relative strength and holds the leaders.",
        "learn": "Momentum can persist, but crowded trends can reverse abruptly.",
        "watch": "Compare drawdown and turnover with the return advantage.",
    },
    "Mean Reversion": {
        "principle": "Buys recent laggards under the assumption that short-term moves partially reverse.",
        "learn": "Contrarian signals can diversify momentum, but may keep buying deteriorating assets.",
        "watch": "Check whether lower turnover or drawdown compensates for weaker growth.",
    },
    "Gradient Boosting": {
        "principle": "Fits a nonlinear model on lagged market features and ranks predicted returns.",
        "learn": "Machine learning can combine weak signals, but time ordering and model stability matter.",
        "watch": "Look for genuine training and prediction evidence, not only attractive metrics.",
    },
    "Hybrid ML + Minimum Variance": {
        "principle": "Combines model forecasts with a covariance-aware allocation.",
        "learn": "Forecast strength and portfolio construction solve different parts of the problem.",
        "watch": "A smoother portfolio can still suffer if the forecast and rebalance horizons disagree.",
    },
}


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _day_key(value: Any) -> str:
    return str(value or "")[:10]


def _downsample(items: list[dict[str, Any]], limit: int = MAX_PUBLIC_CURVE_POINTS) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return items
    if limit < 2:
        return items[-1:]
    selected = {
        round(index * (len(items) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [items[index] for index in sorted(selected)]


def build_performance_analysis(
    details: dict[str, Any] | None,
    summary: dict[str, Any] | None,
    *,
    initial_cash: float,
) -> dict[str, Any]:
    """Create a compact public performance view from trusted Worker details."""

    details = details if isinstance(details, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    snapshots = details.get("position_snapshots")
    if not isinstance(snapshots, list):
        snapshots = []
    raw_equity = details.get("equity_curve")
    if not isinstance(raw_equity, list):
        raw_equity = []

    # Keep the final observation for each day. Fill snapshots otherwise create
    # duplicate x-axis points and make the public chart unnecessarily large.
    daily: dict[str, dict[str, Any]] = {}
    for item in [*raw_equity, *snapshots]:
        if not isinstance(item, dict):
            continue
        day = _day_key(item.get("time"))
        equity = _number(item.get("portfolio_value"))
        if not day or equity is None or equity <= 0:
            continue
        existing = daily.get(day, {})
        daily[day] = {
            "date": day,
            "equity": equity,
            "cash": _number(item.get("cash"), _number(existing.get("cash"), 0.0)),
            "gross_exposure": _number(
                item.get("gross_exposure"),
                _number(existing.get("gross_exposure"), 0.0),
            ),
        }

    equity_curve: list[dict[str, Any]] = []
    peak = 0.0
    base_equity = float(initial_cash)
    daily_returns: list[float] = []
    previous_equity: float | None = None
    for day in sorted(daily):
        point = daily[day]
        equity = float(point["equity"])
        peak = max(peak, equity)
        if previous_equity is not None and previous_equity > 0:
            daily_returns.append(equity / previous_equity - 1.0)
        previous_equity = equity
        equity_curve.append(
            {
                **point,
                "normalized_equity": equity / base_equity if base_equity > 0 else None,
                "drawdown": equity / peak - 1.0 if peak > 0 else 0.0,
            }
        )

    benchmark_daily: dict[str, dict[str, Any]] = {}
    benchmark = details.get("benchmark_curve")
    if isinstance(benchmark, list):
        for item in benchmark:
            if not isinstance(item, dict):
                continue
            day = _day_key(item.get("time"))
            normalized = _number(item.get("normalized_value"))
            if day and normalized is not None and normalized > 0:
                benchmark_daily[day] = {
                    "date": day,
                    "normalized_value": normalized,
                    "equity": base_equity * normalized,
                    "return": normalized - 1.0,
                }

    order_events = details.get("order_events")
    if not isinstance(order_events, list):
        order_events = []
    total_fees = sum(
        abs(_number(item.get("fee"), 0.0) or 0.0)
        for item in order_events
        if isinstance(item, dict)
    )
    gross_traded_value = sum(
        abs(
            (_number(item.get("fill_quantity"), 0.0) or 0.0)
            * (_number(item.get("fill_price"), 0.0) or 0.0)
        )
        for item in order_events
        if isinstance(item, dict)
    )
    filled_event_count = sum(
        1
        for item in order_events
        if isinstance(item, dict)
        and abs(_number(item.get("fill_quantity"), 0.0) or 0.0) > 0
    )

    annualized_volatility = _number(summary.get("annualized_volatility"))
    sortino_ratio = _number(summary.get("sortino_ratio"))
    if len(daily_returns) >= 2:
        if annualized_volatility is None:
            annualized_volatility = statistics.stdev(daily_returns) * math.sqrt(252)
        if sortino_ratio is None:
            downside = [min(value, 0.0) for value in daily_returns]
            downside_deviation = math.sqrt(
                sum(value * value for value in downside) / len(downside)
            )
            if downside_deviation > 0:
                sortino_ratio = (
                    statistics.fmean(daily_returns) * 252
                    / (downside_deviation * math.sqrt(252))
                )

    average_equity = (
        statistics.fmean(point["equity"] for point in equity_curve)
        if equity_curve
        else float(initial_cash)
    )
    duration_years = max(len(equity_curve) / 252.0, 1 / 252.0)
    annualized_turnover = _number(summary.get("portfolio_turnover"))
    if annualized_turnover is None and average_equity > 0:
        annualized_turnover = gross_traded_value / average_equity / duration_years

    ending_equity = _number(summary.get("end_equity"))
    if ending_equity is None and equity_curve:
        ending_equity = float(equity_curve[-1]["equity"])
    total_return = (
        ending_equity / float(initial_cash) - 1.0
        if ending_equity is not None and initial_cash > 0
        else None
    )
    path_drawdown = (
        abs(min(point["drawdown"] for point in equity_curve))
        if equity_curve
        else None
    )
    maximum_drawdown = _number(summary.get("maximum_drawdown"), path_drawdown)

    return {
        "analysis_schema_version": "1.0",
        "equity_curve": _downsample(equity_curve),
        "benchmark_curve": _downsample(
            [benchmark_daily[day] for day in sorted(benchmark_daily)]
        ),
        "statistics": {
            "total_return": total_return,
            "annualized_volatility": annualized_volatility,
            "sortino_ratio": sortino_ratio,
            "maximum_drawdown": maximum_drawdown,
            "annualized_turnover": annualized_turnover,
            "total_fees": _number(summary.get("total_fees"), total_fees),
            "gross_traded_value": gross_traded_value,
            "filled_event_count": filled_event_count,
            "benchmark_total_return": (
                list(benchmark_daily.values())[-1]["return"]
                if benchmark_daily
                else None
            ),
        },
    }


def build_behavior_evidence(details: dict[str, Any]) -> dict[str, Any]:
    orders = details.get("orders")
    if not isinstance(orders, list):
        orders = []
    snapshots = details.get("position_snapshots")
    if not isinstance(snapshots, list):
        snapshots = []
    rebalances = details.get("rebalances")
    if not isinstance(rebalances, list):
        rebalances = []
    signals = details.get("signals")
    if not isinstance(signals, list):
        signals = []
    ml = details.get("ml")
    if not isinstance(ml, dict):
        ml = {}
    training_runs = ml.get("training_runs")
    if not isinstance(training_runs, list):
        training_runs = []
    predictions = ml.get("predictions")
    if not isinstance(predictions, list):
        predictions = []

    filled = [
        order
        for order in orders
        if isinstance(order, dict)
        and str(order.get("status", "")).strip().upper() == "FILLED"
    ]
    rejected_statuses = {"INVALID", "REJECTED"}
    rejected = [
        order
        for order in orders
        if isinstance(order, dict)
        and str(order.get("status", "")).strip().upper() in rejected_statuses
    ]
    canceled_statuses = {"CANCELED", "CANCELLED"}
    canceled = [
        order
        for order in orders
        if isinstance(order, dict)
        and str(order.get("status", "")).strip().upper() in canceled_statuses
    ]
    rebalance_names = [
        str(event.get("name") or "").strip()
        for event in rebalances
        if isinstance(event, dict)
    ]
    fill_times = sorted(
        str(order["time"])
        for order in filled
        if order.get("time") not in (None, "")
    )
    traded_symbols = sorted(
        {
            str(order["symbol"]).strip().upper()
            for order in filled
            if order.get("symbol") not in (None, "")
        }
    )
    invested_snapshots = [
        snapshot
        for snapshot in snapshots
        if isinstance(snapshot, dict)
        and (
            float(snapshot.get("gross_exposure") or 0) > 0
            or any(
                isinstance(position, dict) and bool(position.get("invested"))
                for position in snapshot.get("positions", [])
            )
        )
    ]
    max_gross_exposure = max(
        (
            float(snapshot.get("gross_exposure") or 0)
            for snapshot in snapshots
            if isinstance(snapshot, dict)
        ),
        default=0.0,
    )
    target_events = [
        event
        for event in rebalances
        if isinstance(event, dict)
        and isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("targets"), dict)
        and any(
            abs(float(value or 0)) > 0
            for value in event["payload"]["targets"].values()
        )
    ]
    decision_target_events = [
        event
        for event in target_events
        if str(event.get("name") or "") == "decision_targets"
    ]
    if not decision_target_events:
        decision_target_events = target_events

    rebalance_keys = {
        (str(event.get("time") or ""), str(event.get("name") or ""))
        for event in rebalances
        if isinstance(event, dict)
    }
    transparent_signals = [
        event
        for event in signals
        if isinstance(event, dict)
        and (
            str(event.get("time") or ""),
            str(event.get("name") or ""),
        )
        not in rebalance_keys
    ]
    selected_predictions = [
        item
        for item in predictions
        if isinstance(item, dict) and bool(item.get("selected"))
    ]
    signal_times = {
        str(event.get("time") or "")
        for event in transparent_signals
        if event.get("time")
    }
    prediction_times = {
        str(event.get("time") or "")
        for event in predictions
        if isinstance(event, dict) and event.get("time")
    }
    target_times = {
        str(event.get("time") or "")
        for event in decision_target_events
        if event.get("time")
    }
    training_times = sorted(
        str(event.get("time") or "")
        for event in training_runs
        if isinstance(event, dict) and event.get("time")
    )
    training_before_prediction_count = sum(
        1
        for prediction_time in prediction_times
        if any(training_time <= prediction_time for training_time in training_times)
    )
    return {
        "evidence_schema_version": "2.0",
        "order_count": len(orders),
        "filled_order_count": len(filled),
        "rejected_order_count": len(rejected),
        "canceled_order_count": len(canceled),
        "traded_symbols": traded_symbols,
        "first_fill_time": fill_times[0] if fill_times else None,
        "last_fill_time": fill_times[-1] if fill_times else None,
        "position_snapshot_count": len(snapshots),
        "invested_snapshot_count": len(invested_snapshots),
        "max_gross_exposure": max_gross_exposure,
        "rebalance_count": len(rebalances),
        "staged_rebalance_started_count": rebalance_names.count(
            "decision_targets"
        ),
        "staged_rebalance_completed_count": rebalance_names.count(
            "staged_rebalance_completed"
        ),
        "staged_rebalance_replacement_count": (
            rebalance_names.count("staged_rebalance_replacement_requested")
            + rebalance_names.count("staged_rebalance_replaced")
        ),
        "staged_rebalance_failed_count": rebalance_names.count(
            "staged_rebalance_failed"
        ),
        "latest_rebalance_event": (
            copy.deepcopy(rebalances[-1]) if rebalances else None
        ),
        "nonzero_target_event_count": len(target_events),
        "target_intent_event_count": len(decision_target_events),
        "signal_event_count": len(signals),
        "transparent_signal_event_count": len(transparent_signals),
        "ml_training_run_count": len(training_runs),
        "ml_prediction_count": len(predictions),
        "selected_ml_prediction_count": len(selected_predictions),
        "signal_to_target_link_count": len(signal_times.intersection(target_times)),
        "prediction_to_target_link_count": len(
            prediction_times.intersection(target_times)
        ),
        "hybrid_decision_link_count": len(
            signal_times.intersection(prediction_times, target_times)
        ),
        "training_before_prediction_count": training_before_prediction_count,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_guided_human_source(strategy: GuidedHumanStrategy) -> str:
    """Compile basic or advanced Guided Mode through the fixed template."""

    return compile_strategy_source(_guided_human_strategy_spec(strategy))

    reverse = strategy.signal == "momentum"
    signal_label = "Momentum" if reverse else "Mean reversion"
    date_rule = "week_start" if strategy.rebalance == "weekly" else "month_start"
    return f'''from datetime import datetime

from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm, af_split_history_frames


class UserStrategy(AlphaForgeBaseAlgorithm):
    def _parameter(self, name, default):
        value = self.get_parameter(name)
        return value if value not in (None, "") else default

    def initialize(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2020-01-02"))
        end = datetime.fromisoformat(self._parameter("end_date", "2024-12-31"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.target_gross = 0.90
        self.lookback_days = {strategy.lookback_days}
        self.holdings = {strategy.holdings}
        self.pending_targets = None

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

        self.schedule.on(
            self.date_rules.{date_rule}(self.symbols[0]),
            self.time_rules.after_market_open(self.symbols[0], 30),
            self.rebalance,
        )
        self.set_warm_up(self.lookback_days + 1, Resolution.DAILY)

    def rebalance(self):
        if self.is_warming_up:
            return
        frames = af_split_history_frames(
            self.history(self.symbols, self.lookback_days + 1, Resolution.DAILY)
        )
        scores = {{}}
        for symbol in self.symbols:
            frame = frames.get(symbol.value.upper())
            if frame is None or "close" not in frame or len(frame) < self.lookback_days + 1:
                continue
            closes = frame["close"].dropna()
            if len(closes) < self.lookback_days + 1 or float(closes.iloc[0]) <= 0:
                continue
            scores[symbol] = float(closes.iloc[-1] / closes.iloc[0] - 1)

        ranked = sorted(scores, key=scores.get, reverse={reverse})
        selected = ranked[: min(self.holdings, len(ranked))]
        if not selected:
            self.pending_targets = None
            self.liquidate(tag="No valid {signal_label.lower()} signals")
            return
        weight = self.target_gross / len(selected)
        targets = [PortfolioTarget(symbol, weight) for symbol in selected]
        if self.portfolio.invested:
            self.pending_targets = targets
            self.liquidate(tag="Guided Human · {signal_label} · reduce")
            return
        self.set_holdings(
            targets,
            liquidate_existing_holdings=False,
            tag="Guided Human · {signal_label}",
        )

    def on_data(self, data):
        if (
            self.is_warming_up
            or self.pending_targets is None
            or self.transactions.get_open_orders()
        ):
            return
        targets = self.pending_targets
        self.pending_targets = None
        self.set_holdings(
            targets,
            liquidate_existing_holdings=False,
            tag="Guided Human · {signal_label} · establish",
        )
'''


def _guided_human_strategy_spec(
    strategy: GuidedHumanStrategy,
) -> dict[str, Any]:
    """Map user-friendly presets to the validated fixed-template DSL."""

    primary_weight = strategy.primary_signal_weight
    secondary_weight = round(1.0 - primary_weight, 6)
    recipes: dict[str, list[dict[str, Any]]] = {
        "momentum": [
            {
                "feature": {"kind": "return", "window": strategy.lookback_days},
                "direction": "higher",
                "weight": 1.0,
            }
        ],
        "mean_reversion": [
            {
                "feature": {"kind": "return", "window": strategy.lookback_days},
                "direction": "lower",
                "weight": 1.0,
            }
        ],
        "low_volatility": [
            {
                "feature": {
                    "kind": "volatility",
                    "window": strategy.secondary_lookback_days,
                },
                "direction": "lower",
                "weight": 1.0,
            }
        ],
        "momentum_low_volatility": [
            {
                "feature": {"kind": "return", "window": strategy.lookback_days},
                "direction": "higher",
                "weight": primary_weight,
            },
            {
                "feature": {
                    "kind": "volatility",
                    "window": strategy.secondary_lookback_days,
                },
                "direction": "lower",
                "weight": secondary_weight,
            },
        ],
        "trend_quality": [
            {
                "feature": {
                    "kind": "relative_return",
                    "window": strategy.lookback_days,
                },
                "direction": "higher",
                "weight": primary_weight,
            },
            {
                "feature": {
                    "kind": "sma_gap",
                    "window": strategy.secondary_lookback_days,
                },
                "direction": "higher",
                "weight": secondary_weight,
            },
        ],
    }
    labels = {
        "momentum": "Momentum Rank",
        "mean_reversion": "Mean Reversion",
        "low_volatility": "Low Volatility",
        "momentum_low_volatility": "Momentum and Low Volatility",
        "trend_quality": "Relative Trend Quality",
    }
    return {
        "schema_version": TEMPLATE_VERSION,
        "strategy_name": f"Human Guided - {labels[strategy.signal]}",
        "track": "Traditional",
        "thesis": (
            f"A user-configured {labels[strategy.signal].lower()} strategy "
            "compiled through the fixed AlphaForge template."
        ),
        "signal": {"components": recipes[strategy.signal]},
        "model": None,
        "selection": {
            "top_k": strategy.holdings,
            "require_positive_score": strategy.require_positive_score,
            "hybrid_model_weight": 0.50,
        },
        "portfolio": {
            "weighting": strategy.weighting,
            "gross_exposure": strategy.gross_exposure,
            "max_position_weight": strategy.max_position_weight,
            "volatility_window": strategy.secondary_lookback_days,
            "minimum_variance_blend": 0.0,
            "rebalance_threshold": strategy.rebalance_threshold,
        },
        "schedule": {
            "frequency": strategy.rebalance,
            "minutes_after_open": 30,
        },
        "risk": {
            "market_trend_filter": strategy.market_trend_filter,
            "market_sma_window": strategy.market_sma_window,
            "stop_loss": None,
            "maximum_drawdown": None,
            "cooldown_days": 21,
        },
    }


def _comparison_entries(run: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(run.get("baselines", [])):
        entries.append(
            {
                "id": f"baseline-{index}",
                "label": item.get("name") or f"Baseline {index + 1}",
                "owner": "baseline",
                "track": item.get("family"),
                "state": item.get("state"),
                "summary": copy.deepcopy(item.get("summary") or {}),
                "analysis": copy.deepcopy(item.get("analysis") or {}),
                "behavior_evidence": copy.deepcopy(item.get("behavior_evidence") or {}),
                "explainability": 0.95,
            }
        )
    human = run.get("human") or {}
    entries.append(
        {
            "id": "human",
            "label": "Human Strategy",
            "owner": "human",
            "track": human.get("mode"),
            "state": human.get("state"),
            "summary": copy.deepcopy(human.get("summary") or {}),
            "analysis": copy.deepcopy(human.get("analysis") or {}),
            "behavior_evidence": copy.deepcopy(human.get("behavior_evidence") or {}),
            "explainability": 0.88 if human.get("mode") == "guided" else 0.7,
        }
    )
    for index, item in enumerate(run.get("candidates", [])):
        entries.append(
            {
                "id": f"ai-{str(item.get('track') or index).lower()}",
                "label": f"AI · {item.get('track') or 'Candidate'}",
                "owner": "ai",
                "track": item.get("track"),
                "state": item.get("state"),
                "summary": copy.deepcopy(item.get("summary") or {}),
                "analysis": copy.deepcopy(item.get("analysis") or {}),
                "behavior_evidence": copy.deepcopy(item.get("behavior_evidence") or {}),
                "explainability": 0.9 if item.get("design") else 0.65,
            }
        )
    return entries


def _entry_metric(entry: dict[str, Any], name: str) -> float | None:
    value = _number(entry.get("summary", {}).get(name))
    if value is not None:
        return value
    return _number(entry.get("analysis", {}).get("statistics", {}).get(name))


def _normalized(
    value: float | None,
    values: list[float],
    *,
    lower_is_better: bool = False,
) -> float:
    if value is None or not values:
        return 0.5
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return 0.5
    result = (value - low) / (high - low)
    return 1.0 - result if lower_is_better else result


def build_battle_analysis(run: dict[str, Any]) -> dict[str, Any]:
    """Select the AI champion, judge Human vs AI, and build user-only teaching."""

    entries = _comparison_entries(run)
    for entry in entries:
        required = ("cagr", "sharpe_ratio", "maximum_drawdown", "end_equity")
        missing = [
            name
            for name in required
            if _number(entry["summary"].get(name)) is None
        ]
        expected_state = "accepted" if entry["owner"] == "ai" else "completed"
        reasons: list[str] = []
        if entry["state"] != expected_state:
            reasons.append(
                f"state={entry['state'] or 'unknown'}; required={expected_state}"
            )
        if missing:
            reasons.append("missing comparable metrics: " + ", ".join(missing))
        max_gross = _number(
            entry["behavior_evidence"].get("max_gross_exposure")
        )
        if max_gross is not None and max_gross > 0.98:
            reasons.append(
                f"maximum gross exposure {max_gross:.3f} exceeds the 0.98 execution tolerance"
            )
        entry["eligible"] = not reasons
        entry["eligibility_reasons"] = reasons

    eligible = [entry for entry in entries if entry["eligible"]]
    metric_names = (
        "sharpe_ratio",
        "cagr",
        "maximum_drawdown",
        "annualized_volatility",
        "annualized_turnover",
    )
    metric_values = {
        name: [
            value
            for entry in eligible
            if (value := _entry_metric(entry, name)) is not None
        ]
        for name in metric_names
    }
    initial_cash = _number(run.get("settings", {}).get("initial_cash"), 1.0) or 1.0
    fee_rates = [
        fees / initial_cash
        for entry in eligible
        if (fees := _entry_metric(entry, "total_fees")) is not None
    ]

    scorecards: list[dict[str, Any]] = []
    for entry in entries:
        identity = {
            key: entry[key]
            for key in ("id", "label", "owner", "track", "state")
        }
        if not entry["eligible"]:
            scorecards.append(
                {
                    **identity,
                    "eligible": False,
                    "eligibility_reasons": entry["eligibility_reasons"],
                    "score": None,
                    "components": {},
                    "summary": entry["summary"],
                    "analysis_statistics": entry["analysis"].get("statistics", {}),
                }
            )
            continue

        sharpe = _entry_metric(entry, "sharpe_ratio")
        cagr = _entry_metric(entry, "cagr")
        drawdown = _entry_metric(entry, "maximum_drawdown")
        volatility = _entry_metric(entry, "annualized_volatility")
        turnover = _entry_metric(entry, "annualized_turnover")
        fees = _entry_metric(entry, "total_fees")
        fee_rate = fees / initial_cash if fees is not None else None
        evidence = entry["behavior_evidence"]
        evidence_quality = statistics.fmean(
            [
                1.0 if int(evidence.get("filled_order_count") or 0) > 0 else 0.0,
                1.0 if int(evidence.get("invested_snapshot_count") or 0) > 0 else 0.0,
                1.0 if float(evidence.get("max_gross_exposure") or 0) > 0 else 0.0,
            ]
        )
        cost = (
            0.6
            * _normalized(
                turnover,
                metric_values["annualized_turnover"],
                lower_is_better=True,
            )
            + 0.4 * _normalized(fee_rate, fee_rates, lower_is_better=True)
        )
        components = {
            "sharpe_ratio": round(
                _normalized(sharpe, metric_values["sharpe_ratio"]) * 100,
                2,
            ),
            "cagr": round(
                _normalized(cagr, metric_values["cagr"]) * 100,
                2,
            ),
            "drawdown_control": round(
                _normalized(
                    drawdown,
                    metric_values["maximum_drawdown"],
                    lower_is_better=True,
                )
                * 100,
                2,
            ),
            "volatility_control": round(
                _normalized(
                    volatility,
                    metric_values["annualized_volatility"],
                    lower_is_better=True,
                )
                * 100,
                2,
            ),
            "cost_efficiency": round(cost * 100, 2),
            "execution_evidence": round(evidence_quality * 100, 2),
            "explainability": round(float(entry["explainability"]) * 100, 2),
        }
        score = (
            components["sharpe_ratio"] * 0.35
            + components["cagr"] * 0.30
            + components["drawdown_control"] * 0.15
            + components["volatility_control"] * 0.05
            + components["cost_efficiency"] * 0.05
            + components["execution_evidence"] * 0.05
            + components["explainability"] * 0.05
        )
        scorecards.append(
            {
                **identity,
                "eligible": True,
                "eligibility_reasons": [],
                "score": round(score, 2),
                "components": components,
                "summary": entry["summary"],
                "analysis_statistics": entry["analysis"].get("statistics", {}),
            }
        )

    eligible_cards = [card for card in scorecards if card["eligible"]]
    ai_cards = [card for card in eligible_cards if card["owner"] == "ai"]
    human_card = next(
        (card for card in eligible_cards if card["owner"] == "human"),
        None,
    )
    ai_champion = max(ai_cards, key=lambda card: card["score"]) if ai_cards else None
    contestants = [
        card for card in eligible_cards if card["owner"] in {"human", "ai"}
    ]
    overall_best = max(contestants, key=lambda card: card["score"]) if contestants else None
    reference_cards = [
        card for card in eligible_cards if card["owner"] == "baseline"
    ]
    reference_leader = (
        max(reference_cards, key=lambda card: card["score"])
        if reference_cards
        else None
    )

    if human_card is None and ai_champion is None:
        verdict = {
            "side": "none",
            "label": "No eligible winner",
            "reason": "Neither Human nor AI produced an eligible comparable strategy.",
            "score_gap": None,
        }
    elif ai_champion is None:
        verdict = {
            "side": "human",
            "label": "Human Wins",
            "reason": "No AI candidate passed the deterministic eligibility gates.",
            "score_gap": None,
        }
    elif human_card is None:
        verdict = {
            "side": "ai",
            "label": "AI Wins",
            "reason": "The Human strategy did not produce an eligible completed result.",
            "score_gap": None,
        }
    else:
        gap = round(human_card["score"] - ai_champion["score"], 2)
        if abs(gap) <= 2.0 and not run.get("battle_id"):
            verdict = {
                "side": "draw",
                "label": "Draw",
                "reason": "Composite scores are within the public two-point draw band.",
                "score_gap": gap,
            }
        elif gap > 0 or (
            math.isclose(gap, 0.0)
            and (
                _number(human_card["summary"].get("sharpe_ratio"), 0.0)
                or 0.0
            )
            >= (
                _number(ai_champion["summary"].get("sharpe_ratio"), 0.0)
                or 0.0
            )
        ):
            verdict = {
                "side": "human",
                "label": "Human Wins",
                "reason": "The Human strategy has the higher deterministic composite score.",
                "score_gap": gap,
            }
        else:
            verdict = {
                "side": "ai",
                "label": "AI Wins",
                "reason": "The AI champion has the higher deterministic composite score.",
                "score_gap": gap,
            }

    why_better: list[str] = []
    tradeoffs: list[str] = []
    if overall_best is not None:
        why_better.append(
            f"{overall_best['label']} leads the eligible Human/AI field with a "
            f"{overall_best['score']:.2f}/100 deterministic score."
        )
        for name, label, percent in (
            ("sharpe_ratio", "Sharpe", False),
            ("cagr", "CAGR", True),
            ("maximum_drawdown", "maximum drawdown", True),
        ):
            value = _number(overall_best["summary"].get(name))
            if value is not None:
                rendered = f"{value * 100:.2f}%" if percent else f"{value:.3f}"
                why_better.append(f"{label}: {rendered}.")
        drawdown = _number(overall_best["summary"].get("maximum_drawdown"))
        turnover = _number(
            overall_best["analysis_statistics"].get("annualized_turnover")
        )
        if drawdown is not None and drawdown >= 0.30:
            tradeoffs.append(
                "The return profile still includes a large peak-to-trough loss; sizing and regime controls remain important."
            )
        if turnover is not None and turnover >= 2.0:
            tradeoffs.append(
                "Annualized turnover is high, so live slippage and capacity may be worse than the backtest."
            )
    if not tradeoffs:
        tradeoffs.append(
            "The ranking is conditional on this historical window and does not establish future superiority."
        )

    strengths: list[str] = []
    improvements: list[str] = []
    guided = (run.get("human") or {}).get("guided") or {}
    if human_card is None:
        improvements.extend(
            [
                "First obtain a completed LEAN run with all four comparable summary metrics.",
                "Use the shared rebalance helper and keep a cash buffer so orders can complete.",
                "Record signal-to-target evidence before tuning performance.",
            ]
        )
    elif ai_champion is not None:
        human_sharpe = _number(human_card["summary"].get("sharpe_ratio"), 0.0) or 0.0
        ai_sharpe = _number(ai_champion["summary"].get("sharpe_ratio"), 0.0) or 0.0
        human_dd = _number(human_card["summary"].get("maximum_drawdown"), 1.0) or 1.0
        ai_dd = _number(ai_champion["summary"].get("maximum_drawdown"), 1.0) or 1.0
        human_turnover = _number(
            human_card["analysis_statistics"].get("annualized_turnover")
        )
        ai_turnover = _number(
            ai_champion["analysis_statistics"].get("annualized_turnover")
        )
        if human_sharpe >= ai_sharpe:
            strengths.append(
                f"Human Sharpe is {human_sharpe:.3f} versus AI {ai_sharpe:.3f}; "
                "preserve the current signal/risk balance."
            )
        else:
            if guided:
                current_weighting = guided.get("weighting", "equal")
                improvements.append(
                    f"Sharpe trails AI by {ai_sharpe - human_sharpe:.3f}. Change "
                    f"Weighting from {current_weighting} to inverse_volatility, "
                    "then check whether Sharpe rises without sacrificing CAGR."
                )
            else:
                improvements.append(
                    f"Sharpe trails AI by {ai_sharpe - human_sharpe:.3f}. "
                    "Test volatility-scaled position weights as one isolated code change."
                )
        if human_dd <= ai_dd:
            strengths.append(
                "Drawdown control is at least as strong as the AI champion."
            )
        else:
            if guided:
                current_cap = float(guided.get("max_position_weight", 0.45))
                proposed_cap = max(0.10, round(current_cap - 0.05, 2))
                improvements.append(
                    f"Drawdown is {human_dd:.2%} versus AI {ai_dd:.2%}. Lower "
                    f"Max position weight from {current_cap:.0%} to "
                    f"{proposed_cap:.0%}; keep the signal unchanged to isolate sizing."
                )
            else:
                improvements.append(
                    f"Drawdown is {human_dd:.2%} versus AI {ai_dd:.2%}. "
                    "Reduce the per-symbol cap by five percentage points and retest."
                )
        if (
            human_turnover is not None
            and ai_turnover is not None
            and human_turnover > ai_turnover * 1.15
        ):
            current_band = float(guided.get("rebalance_threshold", 0.02))
            proposed_band = min(0.10, round(current_band + 0.01, 2))
            improvements.append(
                f"Annualized turnover is {human_turnover:.2f} versus AI "
                f"{ai_turnover:.2f}. Raise the rebalance threshold from "
                f"{current_band:.0%} to {proposed_band:.0%} before changing the signal."
            )
    else:
        strengths.append("The Human strategy is the only eligible contestant.")
    if len(improvements) < 2:
        improvements.append(
            "Keep the best parameters fixed and run the delayed-start robustness scenario; "
            "do not call an in-sample score increase a durable improvement."
        )
    if len(improvements) < 3:
        improvements.append(
            "Change only one or two controls next round, record the hypothesis first, "
            "and compare CAGR, Sharpe, drawdown, and turnover together."
        )

    concept = {
        "title": "One-change experiments reduce false lessons",
        "lesson": (
            "When signal, sizing, and trading frequency all change together, a better "
            "score cannot identify which mechanism helped. Hold the other controls fixed "
            "and change one decision at a time."
        ),
        "question": (
            "Which single control will you change next round, and which metric should "
            "improve if your hypothesis is correct?"
        ),
    }
    if human_card is not None and ai_champion is not None:
        human_dd = _number(human_card["summary"].get("maximum_drawdown"), 0.0) or 0.0
        human_cagr = _number(human_card["summary"].get("cagr"), 0.0) or 0.0
        if human_dd > 0.30 or human_dd > (
            _number(ai_champion["summary"].get("maximum_drawdown"), 0.0) or 0.0
        ):
            concept = {
                "title": "Position caps change the path, not the signal",
                "lesson": (
                    f"The Human result paired {human_cagr:.2%} CAGR with "
                    f"{human_dd:.2%} drawdown. A smaller position cap can reduce "
                    "concentration while leaving the stock ranking unchanged."
                ),
                "question": (
                    "If the same stocks are selected at smaller weights, how much CAGR "
                    "would you trade for a materially shallower drawdown?"
                ),
            }

    parameter_recommendations: list[dict[str, Any]] = []
    if human_card is not None:
        human_sharpe = _number(
            human_card["summary"].get("sharpe_ratio"),
            0.0,
        ) or 0.0
        human_dd = _number(
            human_card["summary"].get("maximum_drawdown"),
            0.0,
        ) or 0.0
        human_turnover = _number(
            human_card["analysis_statistics"].get("annualized_turnover")
        )
        ai_sharpe = (
            _number(ai_champion["summary"].get("sharpe_ratio"), 0.0) or 0.0
            if ai_champion
            else None
        )
        ai_dd = (
            _number(ai_champion["summary"].get("maximum_drawdown"), 0.0) or 0.0
            if ai_champion
            else None
        )
        ai_turnover = (
            _number(
                ai_champion["analysis_statistics"].get("annualized_turnover")
            )
            if ai_champion
            else None
        )
        if guided:
            current_weighting = str(guided.get("weighting", "equal"))
            if (
                ai_sharpe is not None
                and human_sharpe < ai_sharpe
                and current_weighting != "inverse_volatility"
            ):
                parameter_recommendations.append(
                    {
                        "parameter_path": "guided.weighting",
                        "label": "Portfolio weighting",
                        "current_value": current_weighting,
                        "recommended_value": "inverse_volatility",
                        "target_metric": "Sharpe ratio",
                        "reason": (
                            f"Human Sharpe {human_sharpe:.3f} trails AI "
                            f"{ai_sharpe:.3f}; scale positions by estimated risk "
                            "without changing the stock signal."
                        ),
                    }
                )
            if ai_dd is not None and human_dd > ai_dd:
                current_cap = float(guided.get("max_position_weight", 0.45))
                gross = float(guided.get("gross_exposure", 0.90))
                holdings = int(guided.get("holdings", 3))
                minimum_cap = gross / max(1, holdings)
                proposed_cap = round(max(minimum_cap, current_cap - 0.05), 2)
                if proposed_cap < current_cap:
                    parameter_recommendations.append(
                        {
                            "parameter_path": "guided.max_position_weight",
                            "label": "Maximum position weight",
                            "current_value": current_cap,
                            "recommended_value": proposed_cap,
                            "target_metric": "Maximum drawdown",
                            "reason": (
                                f"Human drawdown {human_dd:.2%} exceeds AI "
                                f"{ai_dd:.2%}; reduce concentration while keeping "
                                "the signal and gross exposure fixed."
                            ),
                        }
                    )
                else:
                    proposed_gross = round(max(0.50, gross - 0.05), 2)
                    if proposed_gross < gross:
                        parameter_recommendations.append(
                            {
                                "parameter_path": "guided.gross_exposure",
                                "label": "Gross exposure",
                                "current_value": gross,
                                "recommended_value": proposed_gross,
                                "target_metric": "Maximum drawdown",
                                "reason": (
                                    f"Human drawdown {human_dd:.2%} exceeds AI "
                                    f"{ai_dd:.2%}; the position cap cannot fall "
                                    "further without violating portfolio capacity."
                                ),
                            }
                        )
            if (
                human_turnover is not None
                and (
                    human_turnover >= 2.0
                    or (
                        ai_turnover is not None
                        and human_turnover > ai_turnover * 1.15
                    )
                )
            ):
                current_band = float(guided.get("rebalance_threshold", 0.02))
                proposed_band = round(min(0.10, current_band + 0.01), 2)
                if proposed_band > current_band:
                    parameter_recommendations.append(
                        {
                            "parameter_path": "guided.rebalance_threshold",
                            "label": "Rebalance threshold",
                            "current_value": current_band,
                            "recommended_value": proposed_band,
                            "target_metric": "Turnover and fees",
                            "reason": (
                                f"Human annualized turnover is {human_turnover:.2f}; "
                                "a wider no-trade band can suppress small orders."
                            ),
                        }
                    )
        else:
            if ai_dd is not None and human_dd > ai_dd:
                parameter_recommendations.append(
                    {
                        "parameter_path": "code.position_sizing",
                        "label": "Position sizing in your code",
                        "current_value": "current implementation",
                        "recommended_value": "reduce each target weight by 5 percentage points",
                        "target_metric": "Maximum drawdown",
                        "reason": (
                            f"Human drawdown {human_dd:.2%} exceeds AI "
                            f"{ai_dd:.2%}. Keep signal logic unchanged."
                        ),
                    }
                )
            if ai_sharpe is not None and human_sharpe < ai_sharpe:
                parameter_recommendations.append(
                    {
                        "parameter_path": "code.weighting",
                        "label": "Risk scaling in your code",
                        "current_value": "current implementation",
                        "recommended_value": "divide raw weights by trailing volatility",
                        "target_metric": "Sharpe ratio",
                        "reason": (
                            f"Human Sharpe {human_sharpe:.3f} trails AI "
                            f"{ai_sharpe:.3f}; add one risk-scaling step and leave "
                            "the alpha signal unchanged."
                        ),
                    }
                )

    return {
        "schema_version": "1.0",
        "judge": {
            "method": "deterministic_weighted_score_v2",
            "weights": {
                "sharpe_ratio": 0.35,
                "cagr": 0.30,
                "drawdown_control": 0.15,
                "volatility_control": 0.05,
                "cost_efficiency": 0.05,
                "execution_evidence": 0.05,
                "explainability": 0.05,
            },
            "draw_band_points": 0.0 if run.get("battle_id") else 2.0,
            "scorecards": scorecards,
        },
        "ai_champion": copy.deepcopy(ai_champion),
        "reference_leader": copy.deepcopy(reference_leader),
        "overall_best": copy.deepcopy(overall_best),
        "verdict": verdict,
        "education_summary": {
            "llm_state": "pending",
            "llm_review": None,
            "llm_error": None,
            "best_strategy_analysis": {
                "headline": (
                    f"Why {overall_best['label']} leads this round"
                    if overall_best
                    else "No eligible strategy to explain yet"
                ),
                "why_better": why_better,
                "tradeoffs_and_boundaries": tradeoffs,
            },
            "human_feedback": {
                "strengths": strengths,
                "improvements": improvements[:3],
                "parameter_recommendations": parameter_recommendations[:3],
            },
            "knowledge_card": concept,
            "risk_disclaimer": (
                "Historical backtests are educational evidence, not a guarantee of future "
                "returns. Repeated revisions on the same period increase overfitting risk."
            ),
        },
        "baseline_classroom": copy.deepcopy(BASELINE_LESSONS),
    }


def build_robustness_verdict(
    primary_summary: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score stresses with scenario-specific retention and worst-case safeguards."""

    primary_cagr = _number(primary_summary.get("cagr"), 0.0) or 0.0
    primary_sharpe = _number(primary_summary.get("sharpe_ratio"), 0.0) or 0.0
    primary_drawdown = (
        _number(primary_summary.get("maximum_drawdown"), 0.0) or 0.0
    )
    policies = {
        "recent_regime": {
            "weight": 0.35,
            "cagr_retention": 0.55,
            "sharpe_retention": 0.50,
            "drawdown_multiple": 1.35,
            "drawdown_addition": 0.08,
        },
        "delayed_start": {
            "weight": 0.25,
            "cagr_retention": 0.65,
            "sharpe_retention": 0.60,
            "drawdown_multiple": 1.30,
            "drawdown_addition": 0.07,
        },
        "friction_2x": {
            "weight": 0.25,
            "cagr_retention": 0.80,
            "sharpe_retention": 0.75,
            "drawdown_multiple": 1.20,
            "drawdown_addition": 0.05,
        },
        "universe_dropout": {
            "weight": 0.15,
            "cagr_retention": 0.65,
            "sharpe_retention": 0.60,
            "drawdown_multiple": 1.30,
            "drawdown_addition": 0.07,
        },
    }
    evaluated = [
        item
        for item in scenarios
        if item.get("state") != "skipped" and item.get("id") in policies
    ]
    completed_count = 0
    weighted_score = 0.0
    active_weight = 0.0
    scenario_scores: list[float] = []
    critical_failures: list[str] = []

    for scenario in evaluated:
        policy = policies[scenario["id"]]
        summary = scenario.get("summary") or {}
        behavior = scenario.get("behavior_evidence") or {}
        completed = scenario.get("state") == "completed"
        active = (
            completed
            and int(behavior.get("filled_order_count") or 0) > 0
            and float(behavior.get("max_gross_exposure") or 0) > 0
        )
        if completed:
            completed_count += 1
        cagr = _number(summary.get("cagr"), 0.0) or 0.0
        sharpe = _number(summary.get("sharpe_ratio"), 0.0) or 0.0
        drawdown = _number(summary.get("maximum_drawdown"), 1.0) or 1.0
        cagr_retention = cagr / primary_cagr if primary_cagr > 0 else None
        sharpe_retention = (
            sharpe / primary_sharpe if primary_sharpe > 0 else None
        )
        cagr_floor = (
            primary_cagr * policy["cagr_retention"]
            if primary_cagr > 0
            else 0.0
        )
        sharpe_floor = (
            primary_sharpe * policy["sharpe_retention"]
            if primary_sharpe > 0
            else 0.0
        )
        drawdown_ceiling = min(
            0.60,
            max(
                primary_drawdown * policy["drawdown_multiple"],
                primary_drawdown + policy["drawdown_addition"],
            ),
        )
        checks = [
            {
                "id": "completed",
                "label": "LEAN completed",
                "weight": 15,
                "passed": completed,
                "observed": scenario.get("state"),
                "threshold": "completed",
            },
            {
                "id": "active",
                "label": "Strategy remained active",
                "weight": 10,
                "passed": active,
                "observed": int(behavior.get("filled_order_count") or 0),
                "threshold": "filled orders > 0 and exposure > 0",
            },
            {
                "id": "cagr_retention",
                "label": "CAGR retention",
                "weight": 30,
                "passed": completed and cagr >= cagr_floor,
                "observed": cagr,
                "threshold": cagr_floor,
            },
            {
                "id": "sharpe_retention",
                "label": "Sharpe retention",
                "weight": 25,
                "passed": completed and sharpe >= sharpe_floor,
                "observed": sharpe,
                "threshold": sharpe_floor,
            },
            {
                "id": "drawdown_control",
                "label": "Drawdown control",
                "weight": 20,
                "passed": completed and drawdown <= drawdown_ceiling,
                "observed": drawdown,
                "threshold": drawdown_ceiling,
            },
        ]
        scenario_score = (
            sum(check["weight"] for check in checks if check["passed"])
            if completed
            else 0.0
        )
        scenario["checks"] = checks
        scenario["score"] = round(scenario_score, 1)
        scenario["policy_weight"] = policy["weight"]
        scenario["cagr_retention"] = cagr_retention
        scenario["sharpe_retention"] = sharpe_retention
        scenario["drawdown_change"] = drawdown - primary_drawdown
        scenario["thresholds"] = {
            "cagr_retention": policy["cagr_retention"],
            "sharpe_retention": policy["sharpe_retention"],
            "maximum_drawdown": drawdown_ceiling,
        }
        scenario_scores.append(scenario_score)
        active_weight += policy["weight"]
        weighted_score += scenario_score * policy["weight"]
        if not completed or not active:
            critical_failures.append(scenario["id"])

    score = round(weighted_score / active_weight, 1) if active_weight else 0.0
    worst_score = min(scenario_scores) if scenario_scores else 0.0
    if len(evaluated) < 3 or completed_count < len(evaluated):
        grade = "insufficient"
        conclusion = (
            "Every planned stress must complete before a robustness conclusion "
            "is reported."
        )
    elif score >= 75 and worst_score >= 55 and not critical_failures:
        grade = "robust"
        conclusion = (
            "Performance and risk controls remained acceptable across every "
            "completed stress, including the weakest scenario."
        )
    elif score >= 55 and worst_score >= 30 and not critical_failures:
        grade = "mixed"
        conclusion = (
            "The strategy survived all stresses, but at least one assumption "
            "caused material performance or risk deterioration."
        )
    else:
        grade = "fragile"
        conclusion = (
            "At least one stress produced a critical execution failure or "
            "unacceptable deterioration."
        )
    return {
        "policy_version": "deterministic-robustness-v2",
        "score": score,
        "worst_scenario_score": round(worst_score, 1),
        "grade": grade,
        "conclusion": conclusion,
        "completed_scenarios": completed_count,
        "evaluated_scenarios": len(evaluated),
        "critical_failures": critical_failures,
        "scenario_weights": {
            key: value["weight"] for key, value in policies.items()
        },
        "limitations": [
            "These are sensitivity tests on historical data, not proof of future performance.",
            "Recent-regime and delayed-start runs overlap the design sample and are not true out-of-sample tests.",
            "A robust grade requires every planned scenario to complete and the weakest scenario to remain acceptable.",
            "Parameter sweeps are intentionally excluded to reduce repeated-test overfitting.",
        ],
    }


class ForgeService:
    """Run the Forge flow and retain a separate replay trace for every Agent call."""

    def __init__(
        self,
        *,
        worker: LeanWorkerClient,
        designer: Any,
        critic: Any,
        allowed_symbols: set[str],
        allowed_benchmarks: set[str],
        trace_root: Path | None = None,
        history_root: Path | None = None,
        educator: Any | None = None,
        coach: Any | None = None,
        game_repository: Any | None = None,
    ) -> None:
        self.worker = worker
        self.designer = designer
        self.critic = critic
        self.educator = educator
        self.coach = coach
        self.game_repository = game_repository
        self.allowed_symbols = {item.upper() for item in allowed_symbols}
        self.allowed_benchmarks = {item.upper() for item in allowed_benchmarks}
        self._runs: dict[str, dict[str, Any]] = {}
        self._traces: dict[str, dict[str, Any]] = {}
        self.trace_root = trace_root.resolve() if trace_root is not None else None
        if self.trace_root is not None:
            self.trace_root.mkdir(parents=True, exist_ok=True)
        self.history_root = (
            history_root.resolve() if history_root is not None else None
        )
        if self.history_root is not None:
            self.history_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._history_lock = threading.RLock()
        # Forge orchestration is serialized per API process. Work inside one run
        # is parallelized explicitly below so shared run-state mutations remain
        # ordered while independent LEAN jobs can still use separate workers.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge")
        self._education_executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="education")
            if educator is not None
            else None
        )
        self._coach_executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="round-coach")
            if game_repository is not None
            else None
        )

    def _trace_path(self, run_id: str) -> Path:
        if self.trace_root is None:
            raise RuntimeError("Agent trace persistence is not configured")
        if not run_id.startswith("forge-") or not run_id[6:].isalnum():
            raise ValueError("invalid Forge run_id")
        return self.trace_root / f"{run_id}.json"

    @staticmethod
    def _public_run(run: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(run)
        result.pop("_battle_memory", None)
        result.pop("_battle_baselines", None)
        result.pop("_ai_incumbents", None)
        result.pop("user_id", None)
        return result

    def _history_path(self, run_id: str) -> Path:
        if self.history_root is None:
            raise RuntimeError("Forge history persistence is not configured")
        if not run_id.startswith("forge-") or not run_id[6:].isalnum():
            raise ValueError("invalid Forge run_id")
        return self.history_root / f"{run_id}.json"

    @staticmethod
    def _entry_score(summary: dict[str, Any]) -> tuple[float, float, float]:
        """Return the deterministic champion ordering used across battle rounds."""

        def metric(name: str, default: float) -> float:
            value = summary.get(name)
            return default if value is None else float(value)

        return (
            metric("sharpe_ratio", float("-inf")),
            metric("cagr", float("-inf")),
            -metric("maximum_drawdown", float("inf")),
        )

    @classmethod
    def _battle_evidence(
        cls,
        completed_rounds: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Any]]]:
        """Extract reusable Round-1 baselines and each track's all-time champion."""

        baselines = None
        if completed_rounds and completed_rounds[0].get("round_number") == 1:
            first_result = completed_rounds[0].get("result") or {}
            first_baselines = first_result.get("baselines") or []
            if (
                len(first_baselines) == len(BASELINES)
                and all(
                    item.get("state") == "completed"
                    and item.get("summary")
                    and not item.get("restored_with_data_gaps")
                    for item in first_baselines
                )
            ):
                baselines = copy.deepcopy(first_baselines)
                for item in baselines:
                    item["reused_from_round"] = 1
                    item["reused_from_run_id"] = completed_rounds[0].get(
                        "forge_run_id"
                    )

        incumbents: dict[str, dict[str, Any]] = {}
        for completed_round in completed_rounds:
            for candidate in (completed_round.get("result") or {}).get(
                "candidates",
                [],
            ):
                track = candidate.get("track")
                if (
                    track not in DESIGNER_TRACKS
                    or candidate.get("state") != "accepted"
                    or not candidate.get("summary")
                    or not candidate.get("strategy_spec")
                    or not candidate.get("source_code")
                ):
                    continue
                contender = copy.deepcopy(candidate)
                contender["_battle_round_number"] = completed_round.get(
                    "round_number"
                )
                contender["_forge_run_id"] = completed_round.get("forge_run_id")
                current = incumbents.get(track)
                if current is None or cls._entry_score(
                    contender["summary"]
                ) > cls._entry_score(current["summary"]):
                    incumbents[track] = contender
        return baselines, incumbents

    @staticmethod
    def _baseline_evidence(
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "name": baseline.get("name"),
            "family": baseline.get("family"),
            "summary": copy.deepcopy(baseline.get("summary") or {}),
            "performance_profile": copy.deepcopy(
                (baseline.get("analysis") or {}).get("statistics") or {}
            ),
            "execution_profile": {
                key: (baseline.get("behavior_evidence") or {}).get(key)
                for key in (
                    "filled_order_count",
                    "max_gross_exposure",
                    "staged_rebalance_completed_count",
                    "staged_rebalance_replacement_count",
                )
            },
            "public_lesson": copy.deepcopy(
                BASELINE_LESSONS.get(baseline.get("name"), {})
            ),
        }

    def _history_record(self, run: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._public_run(run)
        snapshot["schema_version"] = "3.0"
        snapshot["persistence"] = {
            "kind": "complete_forge_snapshot",
            "saved_at": utc_now(),
        }
        return snapshot

        # Legacy v2 summary builder retained below only as migration documentation.
        human = run["human"]
        candidates = run["candidates"]
        accepted = [
            item
            for item in candidates
            if item.get("state") == "accepted" and item.get("summary")
        ]
        best_ai = (
            max(accepted, key=lambda item: self._entry_score(item["summary"]))
            if accepted
            else None
        )
        human_ready = human.get("state") == "completed" and bool(human.get("summary"))
        if not human_ready and best_ai is None:
            winner = {
                "side": "none",
                "label": "No eligible winner",
                "reason": "Neither side produced an eligible completed strategy.",
            }
        elif best_ai is None:
            winner = {
                "side": "human",
                "label": "Human",
                "reason": "No AI parameter candidate completed an eligible trial.",
            }
        elif not human_ready:
            winner = {
                "side": "ai",
                "label": f"AI · {best_ai['track']}",
                "reason": "Human strategy did not complete.",
            }
        else:
            human_score = self._entry_score(human["summary"])
            ai_score = self._entry_score(best_ai["summary"])
            if human_score >= ai_score:
                winner = {
                    "side": "human",
                    "label": "Human",
                    "reason": "Higher Sharpe, then CAGR, then lower drawdown tie-break.",
                }
            else:
                winner = {
                    "side": "ai",
                    "label": f"AI · {best_ai['track']}",
                    "reason": "Higher Sharpe, then CAGR, then lower drawdown tie-break.",
                }
        battle_analysis = run.get("battle_analysis")
        if isinstance(battle_analysis, dict) and isinstance(
            battle_analysis.get("verdict"),
            dict,
        ):
            winner = copy.deepcopy(battle_analysis["verdict"])
            champion = battle_analysis.get("ai_champion")
            best_ai_track = (
                champion.get("track") if isinstance(champion, dict) else None
            )
        else:
            best_ai_track = best_ai.get("track") if best_ai else None

        return {
            "schema_version": "2.0",
            "run_id": run["run_id"],
            "state": run["state"],
            "stage": run["stage"],
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
            "settings": copy.deepcopy(run["settings"]),
            "human": {
                "state": human.get("state"),
                "summary": copy.deepcopy(human.get("summary") or {}),
                "behavior_evidence": copy.deepcopy(
                    human.get("behavior_evidence") or {}
                ),
                "error": human.get("error"),
            },
            "candidates": [
                {
                    "track": item.get("track"),
                    "state": item.get("state"),
                    "summary": copy.deepcopy(item.get("summary") or {}),
                    "error": item.get("error"),
                    "generation_retries": item.get("generation_retries", 0),
                    "iteration_count": item.get("iteration_count", 0),
                    "design": copy.deepcopy(item.get("design")),
                    "strategy_spec": copy.deepcopy(item.get("strategy_spec")),
                    "best_iteration": item.get("best_iteration"),
                    "iterations": copy.deepcopy(item.get("iterations") or []),
                    "critique_history": copy.deepcopy(
                        item.get("critique_history") or []
                    ),
                }
                for item in candidates
            ],
            "winner": winner,
            "best_ai_track": best_ai_track,
            "battle_analysis": copy.deepcopy(battle_analysis),
            "robustness": copy.deepcopy(run.get("robustness")),
        }

    def _persist_history(self, run_id: str) -> None:
        if self.history_root is None:
            return
        with self._history_lock:
            # Snapshot only after obtaining the write lock. Otherwise an older
            # polling request can copy "pending", wait behind the Education
            # writer, and then overwrite its newer "completed" snapshot.
            with self._lock:
                run = copy.deepcopy(self._runs[run_id])
            record = self._history_record(run)
            path = self._history_path(run_id)
            temporary = path.with_suffix(f".{threading.get_ident()}.json.tmp")
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
            # Completed Forge runs are user history. Do not prune them by match size.

    def list_history(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.history_root is None:
            return []
        records: list[dict[str, Any]] = []
        with self._history_lock:
            for path in self.history_root.glob("forge-*.json"):
                try:
                    records.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records[: max(0, min(limit, 500))]

    def get_history(self, run_id: str) -> dict[str, Any] | None:
        if self.history_root is None:
            return None
        try:
            path = self._history_path(run_id)
        except ValueError:
            return None
        with self._history_lock:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _restore_legacy_history(record: dict[str, Any]) -> dict[str, Any]:
        restored = copy.deepcopy(record)
        analysis = restored.get("battle_analysis") or {}
        if "baselines" not in restored:
            cards = (analysis.get("judge") or {}).get("scorecards") or []
            restored["baselines"] = [
                {
                    "name": card.get("label"),
                    "family": card.get("track") or "Reference",
                    "state": (
                        "completed" if card.get("eligible") else "failed"
                    ),
                    "worker_run_id": None,
                    "summary": card.get("summary") or {},
                    "analysis": {
                        "statistics": card.get("analysis_statistics") or {}
                    },
                    "behavior_evidence": {},
                    "error": None,
                    "restored_with_data_gaps": True,
                }
                for card in cards
                if card.get("owner") == "baseline"
            ]
        restored.setdefault("error", None)
        restored.setdefault("robustness", None)
        restored["restored"] = True
        restored["restored_with_data_gaps"] = True
        return restored

    def _restore_run(self, run_id: str) -> dict[str, Any] | None:
        """Restore a complete snapshot and overlay newer durable round metadata."""

        record = self.get_history(run_id)
        sqlite_record = (
            self.game_repository.restore_run(run_id)
            if self.game_repository is not None
            else None
        )
        if record is not None and record.get("schema_version") == "3.0":
            restored = copy.deepcopy(record)
            restored["restored"] = True
            if sqlite_record is not None:
                restored["battle_id"] = sqlite_record.get("battle_id")
                restored["round_number"] = sqlite_record.get("round_number")
                restored["user_id"] = sqlite_record.get("user_id")
                durable_education = (
                    (sqlite_record.get("battle_analysis") or {}).get(
                        "education_summary"
                    )
                    or {}
                )
                # Education is generated asynchronously after the main snapshot.
                # SQLite may therefore hold a newer terminal result than the
                # corresponding run-history JSON written at run completion.
                if durable_education.get("llm_state") in {
                    "completed",
                    "fallback",
                }:
                    restored.setdefault("battle_analysis", {})[
                        "education_summary"
                    ] = copy.deepcopy(durable_education)
                sqlite_candidates = {
                    item.get("track"): item
                    for item in sqlite_record.get("candidates") or []
                }
                for candidate in restored.get("candidates") or []:
                    durable = sqlite_candidates.get(candidate.get("track")) or {}
                    if not candidate.get("champion_iterations") and durable.get(
                        "champion_iterations"
                    ):
                        candidate["champion_iterations"] = copy.deepcopy(
                            durable["champion_iterations"]
                        )
                        candidate["champion_best_iteration"] = durable.get(
                            "champion_best_iteration"
                        )
            return restored
        if sqlite_record is not None:
            return sqlite_record
        if record is not None:
            return self._restore_legacy_history(record)
        return None

    def _persist_trace_locked(self, run_id: str) -> None:
        if self.trace_root is None:
            return
        path = self._trace_path(run_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._traces[run_id], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _initialize_trace(
        self,
        *,
        run_id: str,
        settings: RunSettings,
    ) -> None:
        trace = {
            "schema_version": "1.1",
            "run_id": run_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "state": "queued",
            "error": None,
            "run_settings": settings.model_dump(mode="json"),
            "baseline_results": [],
            "context_manifest": {
                "ai_forge_includes": [
                    "run_settings",
                    "public_baseline_results",
                    "template_parameter_dsl_v1",
                ],
                "ai_forge_excludes": [
                    "human_source",
                    "human_guided_parameters",
                    "human_results",
                    "human_orders",
                    "education_output",
                ],
            },
            "agent_calls": [],
            "worker_attempts": [],
        }
        with self._lock:
            self._traces[run_id] = trace
            self._persist_trace_locked(run_id)

    def _trace_change(self, run_id: str, **values: Any) -> None:
        with self._lock:
            self._traces[run_id].update(copy.deepcopy(values))
            self._traces[run_id]["updated_at"] = utc_now()
            self._persist_trace_locked(run_id)

    def _record_agent_call(
        self,
        *,
        run_id: str,
        track: str,
        stage: str,
        attempt: int,
        trace: dict[str, Any] | None,
        error: Exception | None = None,
    ) -> None:
        entry = {
            "sequence": 0,
            "track": track,
            "stage": stage,
            "attempt": attempt,
            "call": copy.deepcopy(trace),
        }
        if entry["call"] is None:
            entry["call"] = {
                "request_parameters": None,
                "dynamic_context": None,
                "raw_response": None,
                "error": (
                    {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                    if error is not None
                    else None
                ),
            }
        elif error is not None and entry["call"].get("error") is None:
            entry["call"]["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        with self._lock:
            calls = self._traces[run_id]["agent_calls"]
            entry["sequence"] = len(calls) + 1
            calls.append(entry)
            self._traces[run_id]["updated_at"] = utc_now()
            self._persist_trace_locked(run_id)

    def _record_worker_attempt(
        self,
        *,
        run_id: str,
        track: str,
        attempt: int,
        worker_run_id: str,
        source_code: str,
        parameters: dict[str, str],
        strategy_spec: dict[str, Any] | None = None,
        spec_sha256: str | None = None,
    ) -> None:
        entry = {
            "track": track,
            "attempt": attempt,
            "worker_run_id": worker_run_id,
            "submitted_at": utc_now(),
            "finished_at": None,
            "source_code": source_code,
            "strategy_spec": copy.deepcopy(strategy_spec),
            "strategy_spec_sha256": spec_sha256,
            "template_version": TEMPLATE_VERSION if strategy_spec else None,
            "parameters": copy.deepcopy(parameters),
            "result": None,
            "console_log": None,
            "behavior_evidence": None,
            "outcome": "running",
            "error": None,
        }
        with self._lock:
            self._traces[run_id]["worker_attempts"].append(entry)
            self._traces[run_id]["updated_at"] = utc_now()
            self._persist_trace_locked(run_id)

    def _update_worker_attempt(
        self,
        *,
        run_id: str,
        worker_run_id: str,
        **values: Any,
    ) -> None:
        with self._lock:
            attempts = self._traces[run_id]["worker_attempts"]
            entry = next(
                item for item in attempts if item["worker_run_id"] == worker_run_id
            )
            entry.update(copy.deepcopy(values))
            self._traces[run_id]["updated_at"] = utc_now()
            self._persist_trace_locked(run_id)

    def get_trace(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            trace = self._traces.get(run_id)
            if trace is not None:
                return copy.deepcopy(trace)
        if self.trace_root is None:
            return None
        try:
            path = self._trace_path(run_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def create(
        self,
        settings: RunSettings,
        human_strategy: HumanStrategyRequest,
        *,
        battle_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        unknown = sorted(set(settings.symbols).difference(self.allowed_symbols))
        if unknown:
            raise ValueError(f"stocks are not available in the local dataset: {unknown}")
        if settings.benchmark not in self.allowed_benchmarks:
            raise ValueError(
                f"benchmark must be one of {sorted(self.allowed_benchmarks)}"
            )

        run_id = f"forge-{uuid.uuid4().hex[:12]}"
        battle_memory = None
        battle_baselines = None
        ai_incumbents: dict[str, dict[str, Any]] = {}
        round_number = None
        if battle_id is not None:
            if self.game_repository is None or user_id is None:
                raise ValueError("authenticated battle context is required")
            round_number = self.game_repository.validate_round_start(
                user_id,
                battle_id,
            )
            battle_memory = self.game_repository.latest_coach_memory(battle_id)
            completed_rounds = self.game_repository.completed_round_results(
                battle_id
            )
            battle_baselines, ai_incumbents = self._battle_evidence(
                completed_rounds
            )
        human_source = (
            human_strategy.source_code.strip()
            if human_strategy.mode == "code"
            else build_guided_human_source(human_strategy.guided)
        )
        run = {
            "run_id": run_id,
            "state": "queued",
            "stage": "Waiting to start",
            "settings": settings.model_dump(mode="json"),
            "baselines": [
                {
                    "name": item["name"],
                    "family": item["family"],
                    "state": "waiting",
                    "worker_run_id": None,
                    "summary": {},
                    "analysis": {},
                    "behavior_evidence": {},
                    "error": None,
                }
                for item in BASELINES
            ],
            "human": {
                "mode": human_strategy.mode,
                "guided": (
                    human_strategy.guided.model_dump()
                    if human_strategy.guided is not None
                    else None
                ),
                "state": "waiting",
                "worker_run_id": None,
                "source_code": human_source,
                "summary": {},
                "analysis": {},
                "behavior_evidence": {},
                "error": None,
            },
            "candidates": [
                {
                    "track": track,
                    "state": "waiting",
                    "worker_run_id": None,
                    "source_code": None,
                    "design": None,
                    "strategy_spec": None,
                    "strategy_spec_sha256": None,
                    "template_version": TEMPLATE_VERSION,
                    "summary": {},
                    "analysis": {},
                    "behavior_evidence": {},
                    "error": None,
                    "error_code": None,
                    "usage": {},
                    "generation_retries": 0,
                    "iteration_count": 0,
                    "best_iteration": None,
                    "current_round_best_iteration": None,
                    "current_round_best_summary": {},
                    "selection_origin": None,
                    "retained_from_round": None,
                    "retained_from_run_id": None,
                    "champion_iterations": [],
                    "champion_best_iteration": None,
                    "iterations": [],
                    "critique_history": [],
                    "failure_classification": None,
                }
                for track in DESIGNER_TRACKS
            ],
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "error": None,
            "battle_analysis": None,
            "robustness": None,
            "battle_id": battle_id,
            "round_number": round_number,
            "user_id": user_id,
            "_battle_memory": battle_memory,
            "_battle_baselines": battle_baselines,
            "_ai_incumbents": ai_incumbents,
        }
        if battle_id is not None:
            self.game_repository.attach_round(
                user_id=user_id,
                battle_id=battle_id,
                forge_run_id=run_id,
                settings=settings.model_dump(mode="json"),
                human_strategy=human_strategy.model_dump(mode="json"),
            )
        self._initialize_trace(run_id=run_id, settings=settings)
        with self._lock:
            self._runs[run_id] = run
        self._executor.submit(self._execute, run_id, settings, human_source)
        return self._public_run(run)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            restored = self._restore_run(run_id)
            if restored is not None:
                with self._lock:
                    existing = self._runs.setdefault(run_id, restored)
                    run = existing
        result = self._public_run(run) if run is not None else None
        if (
            result is not None
            and result.get("state") in {"completed", "failed"}
            and self.history_root is not None
        ):
            self._persist_history(run_id)
        return result

    def start_robustness(self, run_id: str, target: str) -> dict[str, Any]:
        if target not in {"best_ai", "human"}:
            raise ValueError("robustness target must be best_ai or human")
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise ValueError("unknown run_id")
            if run.get("state") != "completed":
                raise ValueError("complete the Forge run before robustness testing")
            current = run.get("robustness")
            if isinstance(current, dict) and current.get("state") in {
                "queued",
                "running",
            }:
                return copy.deepcopy(current)
            if target == "human":
                entry = run["human"]
                if entry.get("state") != "completed" or not entry.get("source_code"):
                    raise ValueError("Human strategy is not eligible for robustness testing")
                label = "Human Strategy"
            else:
                accepted = [
                    item
                    for item in run["candidates"]
                    if item.get("state") == "accepted"
                    and item.get("source_code")
                    and item.get("summary")
                ]
                if not accepted:
                    raise ValueError(
                        "No accepted AI strategy is eligible for robustness testing"
                    )
                champion = (run.get("battle_analysis") or {}).get("ai_champion")
                champion_track = (
                    champion.get("track")
                    if isinstance(champion, dict)
                    else None
                )
                entry = next(
                    (
                        item
                        for item in accepted
                        if item.get("track") == champion_track
                    ),
                    max(
                        accepted,
                        key=lambda item: self._entry_score(item["summary"]),
                    ),
                )
                label = f"{entry['track']} Strategy"

            raw_settings = copy.deepcopy(run["settings"])
            start = date.fromisoformat(str(raw_settings["start_date"]))
            end = date.fromisoformat(str(raw_settings["end_date"]))
            span_days = max(2, (end - start).days)
            recent_start = end - timedelta(days=max(365, int(span_days * 0.40)))
            if recent_start <= start:
                recent_start = start + timedelta(days=max(1, span_days // 2))
            delayed_start = start + timedelta(
                days=min(126, max(30, span_days // 5))
            )
            if delayed_start >= end:
                delayed_start = start + timedelta(days=max(1, span_days // 3))

            scenarios = [
                {
                    "id": "recent_regime",
                    "label": "Recent-regime slice",
                    "purpose": "Checks whether the signal survives in the later market regime.",
                    "overrides": {"start_date": recent_start.isoformat()},
                },
                {
                    "id": "delayed_start",
                    "label": "Delayed-start sensitivity",
                    "purpose": "Moves the starting point to detect dependence on one entry date.",
                    "overrides": {"start_date": delayed_start.isoformat()},
                },
                {
                    "id": "friction_2x",
                    "label": "Double-friction stress",
                    "purpose": "Doubles fees and slippage without changing strategy logic.",
                    "overrides": {
                        "transaction_cost_bps": float(
                            raw_settings["transaction_cost_bps"]
                        )
                        * 2,
                        "slippage_bps": float(raw_settings["slippage_bps"]) * 2,
                    },
                },
            ]
            symbols = list(raw_settings["symbols"])
            if len(symbols) > 5:
                reduced = [
                    symbol
                    for index, symbol in enumerate(symbols)
                    if (index + 1) % 5 != 0
                ]
                if len(reduced) >= 5:
                    scenarios.append(
                        {
                            "id": "universe_dropout",
                            "label": "Deterministic universe dropout",
                            "purpose": "Removes every fifth stock to test universe dependence.",
                            "overrides": {"symbols": reduced},
                        }
                    )

            robustness = {
                "schema_version": "1.0",
                "state": "queued",
                "target": target,
                "target_label": label,
                "target_track": entry.get("track"),
                "primary_summary": copy.deepcopy(entry.get("summary") or {}),
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "scenarios": [
                    {
                        **scenario,
                        "state": "waiting",
                        "worker_run_id": None,
                        "settings": {**raw_settings, **scenario["overrides"]},
                        "summary": {},
                        "analysis": {},
                        "behavior_evidence": {},
                        "checks": [],
                        "error": None,
                    }
                    for scenario in scenarios
                ],
                "verdict": None,
                "error": None,
            }
            run["robustness"] = robustness
            run["updated_at"] = utc_now()
            source_code = str(entry["source_code"])
        self._executor.submit(
            self._execute_robustness,
            run_id,
            source_code,
        )
        return copy.deepcopy(robustness)

    def _change_robustness(self, run_id: str, **values: Any) -> None:
        with self._lock:
            robustness = self._runs[run_id].get("robustness")
            if not isinstance(robustness, dict):
                return
            robustness.update(values)
            robustness["updated_at"] = utc_now()
            self._runs[run_id]["updated_at"] = utc_now()

    def _change_robustness_scenario(
        self,
        run_id: str,
        index: int,
        **values: Any,
    ) -> None:
        with self._lock:
            robustness = self._runs[run_id].get("robustness")
            if not isinstance(robustness, dict):
                return
            robustness["scenarios"][index].update(values)
            robustness["updated_at"] = utc_now()
            self._runs[run_id]["updated_at"] = utc_now()

    def _execute_robustness(self, run_id: str, source_code: str) -> None:
        try:
            self._change_robustness(run_id, state="running", error=None)
            with self._lock:
                scenario_count = len(
                    self._runs[run_id]["robustness"]["scenarios"]
                )
            for index in range(scenario_count):
                with self._lock:
                    scenario = copy.deepcopy(
                        self._runs[run_id]["robustness"]["scenarios"][index]
                    )
                validated_settings = RunSettings.model_validate(
                    scenario["settings"]
                )
                self._change_robustness_scenario(
                    run_id,
                    index,
                    state="submitting",
                    error=None,
                )
                submitted = self.worker.submit_custom(
                    source_code,
                    validated_settings.worker_parameters(),
                )
                worker_run_id = submitted["run_id"]
                self._change_robustness_scenario(
                    run_id,
                    index,
                    state="queued",
                    worker_run_id=worker_run_id,
                )
                while True:
                    record = self.worker.job(worker_run_id)
                    worker_state = record.get("state", "failed")
                    self._change_robustness_scenario(
                        run_id,
                        index,
                        state=worker_state,
                    )
                    if worker_state in TERMINAL_STATES:
                        break
                    time.sleep(2)
                if not record.get("result_path"):
                    self._change_robustness_scenario(
                        run_id,
                        index,
                        state="failed",
                        error=(
                            record.get("error")
                            or f"Worker finished with state={worker_state}"
                        ),
                    )
                    continue
                result = self.worker.result(worker_run_id)
                if result.get("status") != "completed":
                    self._change_robustness_scenario(
                        run_id,
                        index,
                        state="failed",
                        summary=result.get("summary", {}),
                        error=(
                            "; ".join(result.get("errors", []))
                            or "LEAN stress run failed"
                        ),
                    )
                    continue
                details = self.worker.details(worker_run_id)
                behavior_evidence = build_behavior_evidence(details)
                analysis = build_performance_analysis(
                    details,
                    result.get("summary", {}),
                    initial_cash=float(validated_settings.initial_cash),
                )
                self._change_robustness_scenario(
                    run_id,
                    index,
                    state="completed",
                    summary=result.get("summary", {}),
                    analysis=analysis,
                    behavior_evidence=behavior_evidence,
                    error=None,
                )
            with self._lock:
                robustness = copy.deepcopy(self._runs[run_id]["robustness"])
            verdict = build_robustness_verdict(
                robustness["primary_summary"],
                robustness["scenarios"],
            )
            self._change_robustness(
                run_id,
                state="completed",
                scenarios=robustness["scenarios"],
                verdict=verdict,
                error=None,
            )
            self._persist_history(run_id)
            if self._education_executor is not None:
                with self._lock:
                    education = (
                        self._runs[run_id]
                        .get("battle_analysis", {})
                        .get("education_summary")
                    )
                    if isinstance(education, dict):
                        education.update(
                            {
                                "llm_state": "pending",
                                "llm_review": None,
                                "llm_error": None,
                            }
                        )
                self._education_executor.submit(
                    self._generate_education_review,
                    run_id,
                )
        except Exception as exc:
            self._change_robustness(
                run_id,
                state="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _change(self, run_id: str, **values: Any) -> None:
        with self._lock:
            self._runs[run_id].update(values)
            self._runs[run_id]["updated_at"] = utc_now()

    def _change_item(
        self,
        run_id: str,
        collection: str,
        index: int,
        **values: Any,
    ) -> None:
        with self._lock:
            self._runs[run_id][collection][index].update(values)
            self._runs[run_id]["updated_at"] = utc_now()

    def _change_human(self, run_id: str, **values: Any) -> None:
        with self._lock:
            self._runs[run_id]["human"].update(values)
            self._runs[run_id]["updated_at"] = utc_now()

    def _wait_for_worker(
        self,
        run_id: str,
        collection: str,
        index: int,
        worker_run_id: str,
    ) -> dict[str, Any]:
        self._change_item(
            run_id,
            collection,
            index,
            state="queued",
            worker_run_id=worker_run_id,
        )
        transient_unknown_run_attempts = 0
        while True:
            try:
                record = self.worker.job(worker_run_id)
            except WorkerClientError as exc:
                # The Worker persists a newly submitted job atomically while its
                # execution thread may update the same record. A very short 404
                # immediately after POST is therefore retriable; other 404s and
                # all other request failures remain terminal.
                if not exc.is_unknown_run or transient_unknown_run_attempts >= 4:
                    raise
                time.sleep(0.25 * (2**transient_unknown_run_attempts))
                transient_unknown_run_attempts += 1
                continue
            state = record.get("state", "failed")
            self._change_item(run_id, collection, index, state=state)
            if state in TERMINAL_STATES:
                break
            time.sleep(2)

        if record.get("result_path"):
            result = self.worker.result(worker_run_id)
            analysis: dict[str, Any] = {}
            behavior_evidence: dict[str, Any] = {}
            if result.get("status") == "completed":
                try:
                    details = self.worker.details(worker_run_id)
                    behavior_evidence = build_behavior_evidence(details)
                    initial_cash = float(
                        self._runs[run_id]["settings"]["initial_cash"]
                    )
                    analysis = build_performance_analysis(
                        details,
                        result.get("summary", {}),
                        initial_cash=initial_cash,
                    )
                except Exception:
                    analysis = {}
                    behavior_evidence = {}
            self._change_item(
                run_id,
                collection,
                index,
                state=result.get("status", state),
                summary=result.get("summary", {}),
                analysis=analysis,
                behavior_evidence=behavior_evidence,
                error=(
                    None
                    if result.get("status") == "completed"
                    else "; ".join(result.get("errors", []))
                ),
            )
            return result

        error = record.get("error") or f"Worker finished with state={state}"
        self._change_item(run_id, collection, index, error=error)
        raise RuntimeError(error)

    def _run_human(
        self,
        *,
        run_id: str,
        source_code: str,
        parameters: dict[str, str],
    ) -> None:
        self._change_human(run_id, state="submitting", error=None)
        submitted = self.worker.submit_custom(source_code, parameters)
        worker_run_id = submitted["run_id"]
        self._change_human(
            run_id,
            state="queued",
            worker_run_id=worker_run_id,
        )
        while True:
            record = self.worker.job(worker_run_id)
            state = record.get("state", "failed")
            self._change_human(run_id, state=state)
            if state in TERMINAL_STATES:
                break
            time.sleep(2)

        if not record.get("result_path"):
            error = record.get("error") or f"Worker finished with state={state}"
            self._change_human(run_id, state="failed", error=error)
            return

        result = self.worker.result(worker_run_id)
        completed = result.get("status") == "completed"
        behavior_evidence: dict[str, Any] = {}
        analysis: dict[str, Any] = {}
        if completed:
            try:
                details = self.worker.details(worker_run_id)
                behavior_evidence = build_behavior_evidence(details)
                analysis = build_performance_analysis(
                    details,
                    result.get("summary", {}),
                    initial_cash=float(parameters["initial_cash"]),
                )
            except Exception:
                behavior_evidence = {}
                analysis = {}
        self._change_human(
            run_id,
            state=result.get("status", state),
            summary=result.get("summary", {}),
            analysis=analysis,
            behavior_evidence=behavior_evidence,
            error=(
                None
                if completed
                else "; ".join(result.get("errors", [])) or "LEAN run failed"
            ),
        )

    @staticmethod
    def _add_usage(total: dict[str, int], addition: dict[str, Any]) -> dict[str, int]:
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        return {
            key: int(total.get(key, 0) or 0) + int(addition.get(key, 0) or 0)
            for key in keys
        }

    def _run_template_candidate(
        self,
        *,
        run_id: str,
        index: int,
        track: str,
        settings: RunSettings,
        parameters: dict[str, str],
        baseline_results: list[dict[str, Any]],
        initial_proposal: dict[str, Any],
        battle_memory: dict[str, Any] | None = None,
        incumbent: dict[str, Any] | None = None,
    ) -> None:
        """Run up to three parameter trials and retain the best completed result."""

        proposal = initial_proposal
        usage = self._add_usage({}, proposal.get("usage", {}))
        iterations: list[dict[str, Any]] = []
        critiques: list[dict[str, Any]] = []
        generation_retries = int(proposal.get("generation_retries", 0) or 0)
        partial_completion_reason: str | None = None
        attempted_iteration_count = 0

        for iteration_number in range(1, MAX_TEMPLATE_BACKTESTS + 1):
            attempted_iteration_count = iteration_number
            self._change_item(
                run_id,
                "candidates",
                index,
                current_iteration=iteration_number,
                pipeline_stage=(
                    f"Preparing LEAN iteration "
                    f"{iteration_number}/{MAX_TEMPLATE_BACKTESTS}"
                ),
            )
            try:
                validated = validate_strategy_spec(proposal["strategy_spec"])
                spec = validated.model_dump(mode="json")
                source = compile_strategy_source(validated)
            except Exception as exc:
                self._trace_change(
                    run_id,
                    last_pipeline_error={
                        "stage": "template_parameter_validation",
                        "track": track,
                        "iteration": iteration_number,
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                )
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="failed",
                    error=PUBLIC_AI_PARAMETER_ERROR,
                    error_code="agent_parameter_schema",
                    failure_classification="agent_parameter_schema",
                )
                return

            canonical = json.dumps(
                spec,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            design = copy.deepcopy(proposal.get("design") or {})
            self._change_item(
                run_id,
                "candidates",
                index,
                state="submitting",
                source_code=source,
                design=design,
                strategy_spec=spec,
                strategy_spec_sha256=digest,
                usage=usage,
                generation_retries=generation_retries,
                error=None,
                error_code=None,
            )

            worker_run_id: str | None = None
            try:
                submitted = self.worker.submit_custom(source, parameters)
                worker_run_id = submitted["run_id"]
                self._record_worker_attempt(
                    run_id=run_id,
                    track=track,
                    attempt=iteration_number,
                    worker_run_id=worker_run_id,
                    source_code=source,
                    parameters=parameters,
                    strategy_spec=spec,
                    spec_sha256=digest,
                )
                result = self._wait_for_worker(
                    run_id,
                    "candidates",
                    index,
                    worker_run_id,
                )
            except Exception as exc:
                internal_error = str(exc)
                partial_completion_reason = PUBLIC_BACKTEST_SERVICE_ERROR
                if worker_run_id is not None:
                    self._update_worker_attempt(
                        run_id=run_id,
                        worker_run_id=worker_run_id,
                        finished_at=utc_now(),
                        outcome="worker_polling_failed",
                        error={
                            "type": type(exc).__name__,
                            "message": internal_error,
                        },
                    )
                if iterations:
                    break
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="failed",
                    error=PUBLIC_BACKTEST_SERVICE_ERROR,
                    error_code="backtest_service_failed",
                    failure_classification="template_or_infrastructure_defect",
                )
                return

            if result.get("status") != "completed":
                message = (
                    "; ".join(result.get("errors", []))
                    or "A schema-valid template strategy failed in LEAN"
                )
                self._update_worker_attempt(
                    run_id=run_id,
                    worker_run_id=worker_run_id,
                    finished_at=utc_now(),
                    result=result,
                    outcome="template_runtime_defect",
                    error={"type": "template_runtime_defect", "message": message},
                )
                partial_completion_reason = PUBLIC_TEMPLATE_RUNTIME_ERROR
                if iterations:
                    break
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="failed",
                    error=PUBLIC_TEMPLATE_RUNTIME_ERROR,
                    error_code="template_runtime_failed",
                    failure_classification="template_or_infrastructure_defect",
                )
                return

            with self._lock:
                snapshot = copy.deepcopy(self._runs[run_id]["candidates"][index])
            summary = copy.deepcopy(snapshot.get("summary") or {})
            analysis = copy.deepcopy(snapshot.get("analysis") or {})
            behavior = copy.deepcopy(snapshot.get("behavior_evidence") or {})
            compact_result = compact_iteration_result(
                iteration=iteration_number,
                summary=summary,
                analysis=analysis,
                behavior_evidence=behavior,
            )
            score_key = self._entry_score(summary)
            iteration = {
                "iteration": iteration_number,
                "state": "completed",
                "worker_run_id": worker_run_id,
                "template_version": TEMPLATE_VERSION,
                "strategy_spec_sha256": digest,
                "strategy_spec": spec,
                "design": design,
                "source_code": source,
                "summary": summary,
                "analysis": analysis,
                "behavior_evidence": behavior,
                "selection_key": [
                    value if math.isfinite(value) else -1.0e12
                    for value in score_key
                ],
                "critique": None,
            }
            iterations.append(iteration)
            self._update_worker_attempt(
                run_id=run_id,
                worker_run_id=worker_run_id,
                finished_at=utc_now(),
                result=result,
                behavior_evidence=behavior,
                outcome="completed_parameter_iteration",
                error=None,
            )
            self._change_item(
                run_id,
                "candidates",
                index,
                state="criticizing",
                iterations=copy.deepcopy(iterations),
                iteration_count=len(iterations),
            )

            prior_results = [
                compact_iteration_result(
                    iteration=item["iteration"],
                    summary=item["summary"],
                    analysis=item["analysis"],
                    behavior_evidence=item["behavior_evidence"],
                )
                for item in iterations[:-1]
            ]
            try:
                evaluated = self.critic.evaluate(
                    track=track,
                    iteration=iteration_number,
                    strategy_spec=spec,
                    iteration_result=compact_result,
                    baseline_results=baseline_results,
                    iteration_history=prior_results,
                )
                self._record_agent_call(
                    run_id=run_id,
                    track=track,
                    stage="critic",
                    attempt=iteration_number,
                    trace=evaluated.get("trace"),
                )
                critique = evaluated["report"]
                usage = self._add_usage(usage, evaluated.get("usage", {}))
                iterations[-1]["critique"] = critique
                critiques.append(
                    {
                        "iteration": iteration_number,
                        "worker_run_id": worker_run_id,
                        "report": copy.deepcopy(critique),
                        "discarded_recommendations": copy.deepcopy(
                            evaluated.get("discarded_recommendations") or []
                        ),
                    }
                )
            except Exception as exc:
                self._record_agent_call(
                    run_id=run_id,
                    track=track,
                    stage="critic",
                    attempt=iteration_number,
                    trace=getattr(exc, "trace", None),
                    error=exc,
                )
                iterations[-1]["critique_error"] = PUBLIC_AI_GENERATION_ERROR
                critique = {
                    "iteration": iteration_number,
                    "diagnosis": (
                        "The backtest completed, but the model-generated critique was "
                        "unavailable after structured-output retries."
                    ),
                    "strengths": [
                        "This parameter set completed the fixed-template LEAN backtest."
                    ],
                    "weaknesses": [
                        "No reliable model-generated interpretation is available."
                    ],
                    "preserve": [],
                    "recommended_changes": [],
                    "overfitting_warning": (
                        "Make only one conservative active-parameter revision and "
                        "treat all three trials as exploratory."
                    ),
                }
                iterations[-1]["critique"] = critique
                critiques.append(
                    {
                        "iteration": iteration_number,
                        "worker_run_id": worker_run_id,
                        "report": copy.deepcopy(critique),
                        "fallback": True,
                        "error": str(exc),
                    }
                )

            self._change_item(
                run_id,
                "candidates",
                index,
                usage=usage,
                iterations=copy.deepcopy(iterations),
                critique_history=copy.deepcopy(critiques),
            )
            if iteration_number == MAX_TEMPLATE_BACKTESTS:
                break

            try:
                proposal = self.designer.generate(
                    track=track,
                    run_settings=settings.model_dump(mode="json"),
                    baseline_results=baseline_results,
                    iteration=iteration_number + 1,
                    previous_spec=spec,
                    critique=critique,
                    iteration_history=[
                        compact_iteration_result(
                            iteration=item["iteration"],
                            summary=item["summary"],
                            analysis=item["analysis"],
                            behavior_evidence=item["behavior_evidence"],
                        )
                        for item in iterations
                    ],
                    battle_memory=battle_memory,
                    incumbent=incumbent,
                )
                self._record_agent_call(
                    run_id=run_id,
                    track=track,
                    stage="designer_revision",
                    attempt=iteration_number + 1,
                    trace=proposal.get("trace"),
                )
                usage = self._add_usage(usage, proposal.get("usage", {}))
                generation_retries += int(
                    proposal.get("generation_retries", 0) or 0
                )
            except Exception as exc:
                self._record_agent_call(
                    run_id=run_id,
                    track=track,
                    stage="designer_revision",
                    attempt=iteration_number + 1,
                    trace=getattr(exc, "trace", None),
                    error=exc,
                )
                _, public_error = public_agent_failure(getattr(exc, "trace", None))
                iterations[-1]["revision_error"] = public_error
                break

        if not iterations:
            self._change_item(
                run_id,
                "candidates",
                index,
                state="failed",
                error="No parameter iteration completed",
                error_code="no_completed_trial",
                failure_classification="agent_or_platform_failure",
            )
            return

        current_best = max(
            iterations,
            key=lambda item: tuple(item["selection_key"]),
        )
        retained_incumbent = bool(
            incumbent
            and incumbent.get("summary")
            and incumbent.get("source_code")
            and incumbent.get("strategy_spec")
            and self._entry_score(incumbent["summary"])
            >= self._entry_score(current_best["summary"])
        )
        best = incumbent if retained_incumbent else current_best
        self._change_item(
            run_id,
            "candidates",
            index,
            state="accepted",
            worker_run_id=best.get("worker_run_id"),
            source_code=best["source_code"],
            design=best["design"],
            strategy_spec=best["strategy_spec"],
            strategy_spec_sha256=best["strategy_spec_sha256"],
            summary=copy.deepcopy(best["summary"]),
            analysis=copy.deepcopy(best["analysis"]),
            behavior_evidence=copy.deepcopy(best["behavior_evidence"]),
            usage=usage,
            generation_retries=generation_retries,
            iteration_count=len(iterations),
            best_iteration=(
                best.get("best_iteration")
                if retained_incumbent
                else current_best["iteration"]
            ),
            iterations=copy.deepcopy(iterations),
            critique_history=copy.deepcopy(critiques),
            attempted_iteration_count=attempted_iteration_count,
            partial_completion=attempted_iteration_count > len(iterations),
            partial_completion_reason=partial_completion_reason,
            failure_classification=None,
            error=None,
            error_code=None,
            selection_origin=(
                "prior_round_incumbent"
                if retained_incumbent
                else "current_round"
            ),
            current_round_best_iteration=current_best["iteration"],
            current_round_best_summary=copy.deepcopy(current_best["summary"]),
            retained_from_round=(
                incumbent.get("_battle_round_number")
                if retained_incumbent
                else None
            ),
            retained_from_run_id=(
                incumbent.get("_forge_run_id")
                if retained_incumbent
                else None
            ),
            champion_iterations=copy.deepcopy(
                (
                    incumbent.get("champion_iterations")
                    or incumbent.get("iterations")
                    or []
                )
                if retained_incumbent
                else iterations
            ),
            champion_best_iteration=(
                (
                    incumbent.get("champion_best_iteration")
                    or incumbent.get("best_iteration")
                )
                if retained_incumbent
                else current_best["iteration"]
            ),
        )

    def _run_public_baseline(
        self,
        *,
        run_id: str,
        index: int,
        parameters: dict[str, str],
    ) -> dict[str, Any]:
        """Execute one independent public baseline and return its evidence."""

        baseline = BASELINES[index]
        self._change_item(run_id, "baselines", index, state="submitting")
        submitted = self.worker.submit(baseline["strategy_id"], parameters)
        result = self._wait_for_worker(
            run_id,
            "baselines",
            index,
            submitted["run_id"],
        )
        if result.get("status") != "completed":
            raise RuntimeError(f"{baseline['name']} did not complete")
        with self._lock:
            snapshot = copy.deepcopy(self._runs[run_id]["baselines"][index])
        return {
            "name": baseline["name"],
            "family": baseline["family"],
            "summary": result.get("summary", {}),
            "performance_profile": copy.deepcopy(
                snapshot.get("analysis", {}).get("statistics", {})
            ),
            "execution_profile": {
                key: snapshot.get("behavior_evidence", {}).get(key)
                for key in (
                    "filled_order_count",
                    "max_gross_exposure",
                    "staged_rebalance_completed_count",
                    "staged_rebalance_replacement_count",
                )
            },
            "public_lesson": copy.deepcopy(
                BASELINE_LESSONS.get(baseline["name"], {})
            ),
        }

    @staticmethod
    def _coach_evidence(run: dict[str, Any]) -> dict[str, Any]:
        """Build the cross-round context without any Human-private evidence."""

        public_baselines = [
            {
                "name": item.get("name"),
                "family": item.get("family"),
                "summary": copy.deepcopy(item.get("summary") or {}),
            }
            for item in run.get("baselines", [])
        ]
        strongest_baseline = max(
            public_baselines,
            key=lambda item: ForgeService._entry_score(item["summary"]),
            default=None,
        )
        ai_candidates = [
            {
                "track": item.get("track"),
                "state": item.get("state"),
                "best_iteration": item.get("best_iteration"),
                "selection_origin": item.get("selection_origin"),
                "retained_from_round": item.get("retained_from_round"),
                "current_round_best_iteration": item.get(
                    "current_round_best_iteration"
                ),
                "current_round_best_summary": copy.deepcopy(
                    item.get("current_round_best_summary") or {}
                ),
                "strategy_spec": copy.deepcopy(item.get("strategy_spec")),
                "summary": copy.deepcopy(item.get("summary") or {}),
                "iterations": [
                    {
                        "iteration": iteration.get("iteration"),
                        "summary": copy.deepcopy(
                            iteration.get("summary") or {}
                        ),
                        "strategy_spec": copy.deepcopy(
                            iteration.get("strategy_spec")
                        ),
                        "critique": copy.deepcopy(
                            iteration.get("critique") or {}
                        ),
                    }
                    for iteration in item.get("iterations", [])
                ],
            }
            for item in run.get("candidates", [])
        ]
        diagnostics = [
            ForgeService._coach_track_diagnostic(
                candidate,
                strongest_baseline,
            )
            for candidate in ai_candidates
        ]
        return {
            "run_id": run.get("run_id"),
            "public_baselines": public_baselines,
            "ai_candidates": ai_candidates,
            "computed_track_diagnostics": diagnostics,
        }

    @staticmethod
    def _coach_track_diagnostic(
        candidate: dict[str, Any],
        strongest_baseline: dict[str, Any] | None,
    ) -> dict[str, Any]:
        iterations = candidate.get("iterations") or []
        completed = [
            item for item in iterations if item.get("summary")
        ]
        initial = (completed[0].get("summary") or {}) if completed else {}
        current_best = (
            max(
                completed,
                key=lambda item: ForgeService._entry_score(item["summary"]),
            ).get("summary")
            if completed
            else candidate.get("current_round_best_summary") or {}
        )

        def metric(summary: dict[str, Any], key: str) -> float:
            return _number(summary.get(key), 0.0)

        sharpe_gain = metric(current_best, "sharpe_ratio") - metric(
            initial,
            "sharpe_ratio",
        )
        cagr_gain = metric(current_best, "cagr") - metric(initial, "cagr")
        drawdown_reduction = metric(initial, "maximum_drawdown") - metric(
            current_best,
            "maximum_drawdown",
        )
        meaningful_gain = (
            sharpe_gain >= 0.05
            or cagr_gain >= 0.02
            or drawdown_reduction >= 0.02
        )
        retained = (
            candidate.get("selection_origin") == "prior_round_incumbent"
        )
        baseline_summary = (
            strongest_baseline.get("summary") or {}
            if strongest_baseline
            else {}
        )
        materially_behind = bool(
            strongest_baseline
            and metric(current_best, "sharpe_ratio") + 0.25
            < metric(baseline_summary, "sharpe_ratio")
            and metric(current_best, "cagr")
            <= metric(baseline_summary, "cagr")
        )
        if materially_behind and not meaningful_gain:
            next_move = "rebuild_track"
        elif retained or (len(completed) >= 2 and not meaningful_gain):
            next_move = "rotate_mechanism"
        else:
            next_move = "refine_parameters"
        track = candidate.get("track")
        scope = {
            "Traditional": "signal",
            "ML": "model",
            "Hybrid": "multi_component",
        }.get(track, "portfolio")
        return {
            "track": track,
            "completed_trials": len(completed),
            "historical_champion_retained": retained,
            "retained_from_round": candidate.get("retained_from_round"),
            "sharpe_gain_vs_first_trial": round(sharpe_gain, 6),
            "cagr_gain_vs_first_trial": round(cagr_gain, 6),
            "drawdown_reduction_vs_first_trial": round(
                drawdown_reduction,
                6,
            ),
            "meaningful_trial_improvement": meaningful_gain,
            "strongest_public_baseline": (
                strongest_baseline.get("name")
                if strongest_baseline
                else None
            ),
            "materially_behind_public_reference": materially_behind,
            "recommended_next_move": next_move,
            "recommended_change_scope": scope,
            "recommended_parameter_change_budget": {
                "refine_parameters": 2,
                "rotate_mechanism": 2,
                "rebuild_track": 4,
            }[next_move],
        }

    @staticmethod
    def _fallback_coach_memory(
        round_number: int,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        lessons = []
        diagnostics = {
            item.get("track"): item
            for item in evidence.get("computed_track_diagnostics", [])
        }
        for candidate in evidence.get("ai_candidates", []):
            track = candidate.get("track")
            summary = candidate.get("summary") or {}
            sharpe = _number(summary.get("sharpe_ratio"), 0.0)
            cagr = _number(summary.get("cagr"), 0.0)
            drawdown = _number(summary.get("maximum_drawdown"), 0.0)
            iterations = candidate.get("iterations") or []
            latest_critique = (
                (iterations[-1].get("critique") or {}) if iterations else {}
            )
            diagnostic = diagnostics.get(track) or {}
            next_move = diagnostic.get(
                "recommended_next_move",
                "refine_parameters",
            )
            scope = diagnostic.get(
                "recommended_change_scope",
                "multi_component",
            )
            hypotheses = {
                "Traditional": {
                    "refine_parameters": "Refine one signal window or component weight while preserving the current feature family.",
                    "rotate_mechanism": "Replace the primary feature family, for example return momentum with relative return, RSI, or volatility, while keeping risk controls stable.",
                    "rebuild_track": "Build a distinct transparent multi-factor rank with a new signal family and conservative portfolio controls.",
                },
                "ML": {
                    "refine_parameters": "Refine one model regularization or training-window control without changing the fitted-model mechanism.",
                    "rotate_mechanism": "Change the model algorithm or its core feature set while preserving portfolio and risk controls.",
                    "rebuild_track": "Test a materially different supported model and feature hypothesis with simpler bounded complexity.",
                },
                "Hybrid": {
                    "refine_parameters": "Refine the model-versus-signal blend or one component weight while preserving both causal paths.",
                    "rotate_mechanism": "Replace either the transparent signal family or ML feature/model mechanism, but not both in one trial.",
                    "rebuild_track": "Rebuild the Hybrid interaction with a distinct signal, fitted model, and conservative blend.",
                },
            }.get(track, {})
            lessons.append(
                {
                    "track": track,
                    "evidence_summary": (
                        f"Round {round_number}: CAGR {cagr:.2%}, Sharpe "
                        f"{sharpe:.3f}, maximum drawdown {drawdown:.2%}."
                    ),
                    "preserve": (
                        latest_critique.get("preserve")
                        or ["Retain the best completed template configuration."]
                    )[:3],
                    "avoid": (
                        latest_critique.get("weaknesses")
                        or ["Avoid increasing complexity without measured benefit."]
                    )[:3],
                    "next_hypotheses": [
                        hypotheses.get(
                            next_move,
                            "Test one bounded active-parameter change and compare all risk metrics.",
                        )
                    ],
                    "next_move": next_move,
                    "change_scope": scope,
                    "decision_reason": (
                        "The historical champion was retained, so further small "
                        "adjustments should give way to a different mechanism."
                        if diagnostic.get("historical_champion_retained")
                        else "The decision follows measured trial improvement and the gap to the strongest public reference."
                    ),
                    "parameter_change_budget": int(
                        diagnostic.get(
                            "recommended_parameter_change_budget",
                            2,
                        )
                    ),
                }
            )
        return {
            "round_number": round_number,
            "round_summary": (
                "Deterministic fallback memory was built from completed AI and "
                "public backtests because the model-generated coaching was unavailable."
            ),
            "track_lessons": lessons,
            "overfitting_guard": (
                "Change one mechanism at a time and use robustness evidence before "
                "treating an in-sample gain as an improvement."
            ),
        }

    def _generate_round_coaching(
        self,
        run_id: str,
        round_number: int,
        previous_memory: dict[str, Any] | None,
    ) -> None:
        if self.game_repository is None:
            return
        with self._lock:
            run = copy.deepcopy(self._runs[run_id])
        evidence = self._coach_evidence(run)
        state = "completed"
        try:
            if self.coach is None:
                raise RuntimeError("AI Coach is not configured")
            result = self.coach.reflect(
                round_number=round_number,
                evidence=evidence,
                previous_memory=previous_memory,
            )
            memory = result["memory"]
            self._record_agent_call(
                run_id=run_id,
                track="AI Coach",
                stage="cross_round_reflection",
                attempt=1,
                trace=result.get("trace"),
            )
        except Exception as exc:
            state = "fallback"
            memory = self._fallback_coach_memory(round_number, evidence)
            self._record_agent_call(
                run_id=run_id,
                track="AI Coach",
                stage="cross_round_reflection",
                attempt=1,
                trace=getattr(exc, "trace", None),
                error=exc,
            )
        self.game_repository.save_coach_memory(
            run_id,
            memory,
            state=state,
        )

    @staticmethod
    def _education_evidence(run: dict[str, Any]) -> dict[str, Any]:
        analysis = run.get("battle_analysis") or {}
        champion = analysis.get("overall_best") or analysis.get("ai_champion")
        champion_id = champion.get("id") if isinstance(champion, dict) else None
        champion_spec: dict[str, Any] | None = None
        iterations: list[dict[str, Any]] = []
        if champion_id == "human":
            guided = (run.get("human") or {}).get("guided")
            champion_spec = (
                _guided_human_strategy_spec(
                    GuidedHumanStrategy.model_validate(guided)
                )
                if isinstance(guided, dict)
                else None
            )
        elif isinstance(champion_id, str) and champion_id.startswith("ai-"):
            champion_track = champion.get("track")
            candidate = next(
                (
                    item
                    for item in run.get("candidates", [])
                    if item.get("track") == champion_track
                ),
                None,
            )
            if candidate:
                champion_spec = copy.deepcopy(candidate.get("strategy_spec"))
                iterations = [
                    {
                        "iteration": item.get("iteration"),
                        "selected_as_best": item.get("selected_as_best"),
                        "summary": copy.deepcopy(item.get("summary") or {}),
                        "strategy_spec": copy.deepcopy(item.get("strategy_spec")),
                        "critic": copy.deepcopy(item.get("critique") or {}),
                    }
                    for item in candidate.get("iterations", [])
                ]
        return {
            "run_id": run.get("run_id"),
            "winner": copy.deepcopy(analysis.get("verdict") or {}),
            "champion": copy.deepcopy(champion or {}),
            "reference_leader": copy.deepcopy(
                analysis.get("reference_leader") or {}
            ),
            "score_policy": copy.deepcopy(
                (analysis.get("judge") or {}).get("weights") or {}
            ),
            "scorecards": copy.deepcopy(
                (analysis.get("judge") or {}).get("scorecards") or []
            ),
            "champion_strategy_spec": champion_spec,
            "champion_iterations": iterations,
            "robustness": copy.deepcopy(run.get("robustness")),
        }

    def _generate_education_review(self, run_id: str) -> None:
        if self.educator is None:
            return
        try:
            with self._lock:
                run = copy.deepcopy(self._runs[run_id])
            evidence = self._education_evidence(run)
            result = self.educator.explain(evidence=evidence)
            review = result["review"]
            allowed_paths = {
                "selection.top_k",
                "selection.require_positive_score",
                "portfolio.gross_exposure",
                "portfolio.max_position_weight",
                "portfolio.volatility_window",
                "portfolio.rebalance_threshold",
                "schedule.frequency",
                "risk.market_trend_filter",
                "risk.market_sma_window",
            }
            for action in review.get("next_round_actions", []):
                path = str(action.get("parameter_path") or "")
                if path.startswith("strategy_spec."):
                    path = path[len("strategy_spec.") :]
                    action["parameter_path"] = path
                if path not in allowed_paths:
                    raise ValueError(
                        f"Teaching Explainer suggested unsupported parameter: {path}"
                    )
                current: Any = evidence.get("champion_strategy_spec")
                for part in path.split("."):
                    if not isinstance(current, dict) or part not in current:
                        raise ValueError(
                            f"Teaching Explainer parameter is absent from champion: {path}"
                        )
                    current = current[part]
                action["current_value"] = str(current)
            self._record_agent_call(
                run_id=run_id,
                track="Education",
                stage="teaching_explainer",
                attempt=1,
                trace=result.get("trace"),
            )
            with self._lock:
                education = self._runs[run_id]["battle_analysis"][
                    "education_summary"
                ]
                education.update(
                    {
                        "llm_state": "completed",
                        "llm_review": review,
                        "llm_error": None,
                    }
                )
                self._runs[run_id]["updated_at"] = utc_now()
                education_snapshot = copy.deepcopy(education)
            self._persist_history(run_id)
            if self.game_repository is not None:
                self.game_repository.update_round_education(
                    run_id,
                    education_snapshot,
                )
        except Exception as exc:
            failed_trace = getattr(exc, "trace", None)
            self._record_agent_call(
                run_id=run_id,
                track="Education",
                stage="teaching_explainer",
                attempt=1,
                trace=failed_trace,
                error=exc,
            )
            with self._lock:
                analysis = self._runs[run_id].get("battle_analysis") or {}
                education = analysis.get("education_summary") or {}
                education.update(
                    {
                        "llm_state": "fallback",
                        "llm_review": None,
                        "llm_error": str(exc),
                    }
                )
                self._runs[run_id]["updated_at"] = utc_now()
                education_snapshot = copy.deepcopy(education)
            self._persist_history(run_id)
            if self.game_repository is not None:
                self.game_repository.update_round_education(
                    run_id,
                    education_snapshot,
                )

    def _execute(
        self,
        run_id: str,
        settings: RunSettings,
        human_source: str,
    ) -> None:
        parameters = settings.worker_parameters()
        with self._lock:
            battle_memory = copy.deepcopy(
                self._runs[run_id].get("_battle_memory")
            )
            battle_baselines = copy.deepcopy(
                self._runs[run_id].get("_battle_baselines")
            )
            ai_incumbents = copy.deepcopy(
                self._runs[run_id].get("_ai_incumbents") or {}
            )
        try:
            if battle_baselines:
                self._change(
                    run_id,
                    state="running",
                    stage="Reusing frozen Round 1 baseline evidence",
                    baselines=[
                        {
                            **item,
                            "reused_from_round": 1,
                            "baseline_execution": "reused",
                        }
                        for item in battle_baselines
                    ],
                )
                evidence = [
                    self._baseline_evidence(item)
                    for item in battle_baselines
                ]
            else:
                self._change(
                    run_id,
                    state="running",
                    stage="Running four public baselines in parallel",
                )
                # Preserve catalog order in the public response even though
                # isolated workers complete in a nondeterministic order.
                evidence_by_index: dict[int, dict[str, Any]] = {}
                baseline_errors: dict[int, Exception] = {}
                with ThreadPoolExecutor(
                    max_workers=len(BASELINES),
                    thread_name_prefix="baseline",
                ) as baseline_executor:
                    baseline_futures = {
                        baseline_executor.submit(
                            self._run_public_baseline,
                            run_id=run_id,
                            index=index,
                            parameters=parameters,
                        ): index
                        for index in range(len(BASELINES))
                    }
                    for future in as_completed(baseline_futures):
                        index = baseline_futures[future]
                        try:
                            evidence_by_index[index] = future.result()
                        except Exception as exc:
                            baseline_errors[index] = exc
                            self._change_item(
                                run_id,
                                "baselines",
                                index,
                                state="failed",
                                error=str(exc),
                            )
                if baseline_errors:
                    failures = "; ".join(
                        f"{BASELINES[index]['name']}: {error}"
                        for index, error in sorted(baseline_errors.items())
                    )
                    raise RuntimeError(
                        f"Public baseline batch failed: {failures}"
                    )
                evidence = [
                    evidence_by_index[index]
                    for index in range(len(BASELINES))
                ]

            for metric, lower_is_better in (
                ("sharpe_ratio", False),
                ("cagr", False),
                ("maximum_drawdown", True),
            ):
                ranked = sorted(
                    evidence,
                    key=lambda item: _number(
                        item.get("summary", {}).get(metric),
                        float("inf") if lower_is_better else float("-inf"),
                    ),
                    reverse=not lower_is_better,
                )
                for rank, item in enumerate(ranked, start=1):
                    item.setdefault("public_ranks", {})[metric] = rank

            self._trace_change(run_id, baseline_results=evidence, state="running")

            self._change(
                run_id,
                stage="Generating three Designer candidates in parallel · Running Human strategy",
            )
            # Designers never receive Human output. Running Human work in the
            # calling thread overlaps latency without crossing that boundary.
            generated_candidates: dict[int, dict[str, Any]] = {}
            with ThreadPoolExecutor(
                max_workers=len(DESIGNER_TRACKS),
                thread_name_prefix="designer",
            ) as designer_executor:
                futures: dict[Future, tuple[int, str]] = {}
                for index, track in enumerate(DESIGNER_TRACKS):
                    self._change_item(
                        run_id,
                        "candidates",
                        index,
                        state="generating",
                        error=None,
                        error_code=None,
                    )
                    future = designer_executor.submit(
                        self.designer.generate,
                        track=track,
                        run_settings=settings.model_dump(mode="json"),
                        baseline_results=evidence,
                        battle_memory=battle_memory,
                        incumbent=ai_incumbents.get(track),
                    )
                    futures[future] = (index, track)

                try:
                    self._run_human(
                        run_id=run_id,
                        source_code=human_source,
                        parameters=parameters,
                    )
                except Exception as exc:
                    self._change_human(run_id, state="failed", error=str(exc))

                self._change(
                    run_id,
                    stage="Collecting three parallel Designer responses",
                )
                for future in as_completed(futures):
                    index, track = futures[future]
                    try:
                        generated = future.result()
                        self._record_agent_call(
                            run_id=run_id,
                            track=track,
                            stage="designer",
                            attempt=1,
                            trace=generated.get("trace"),
                        )
                        generated_candidates[index] = generated
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="generated",
                            design=generated.get("design"),
                            strategy_spec=generated.get("strategy_spec"),
                            usage=self._add_usage({}, generated.get("usage", {})),
                            generation_retries=int(
                                generated.get("generation_retries", 0) or 0
                            ),
                            error=None,
                            error_code=None,
                        )
                    except Exception as exc:
                        failed_trace = getattr(exc, "trace", None)
                        error_code, public_error = public_agent_failure(failed_trace)
                        self._record_agent_call(
                            run_id=run_id,
                            track=track,
                            stage="designer",
                            attempt=1,
                            trace=failed_trace,
                            error=exc,
                        )
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="failed",
                            generation_retries=int(
                                (failed_trace or {}).get(
                                    "semantic_retry_count",
                                    0,
                                )
                                or 0
                            ),
                            error=public_error,
                            error_code=error_code,
                            failure_classification=error_code,
                        )

            self._change(
                run_id,
                stage="Running three independent AI candidate pipelines in parallel",
            )
            # Each track iterates sequentially (LEAN -> Critic -> Designer), but
            # the three tracks are independent and may occupy different workers.
            with ThreadPoolExecutor(
                max_workers=len(DESIGNER_TRACKS),
                thread_name_prefix="candidate",
            ) as candidate_executor:
                candidate_futures: dict[Future, tuple[int, str]] = {}
                for index, track in enumerate(DESIGNER_TRACKS):
                    generated = generated_candidates.get(index)
                    if generated is None:
                        continue
                    future = candidate_executor.submit(
                        self._run_template_candidate,
                        run_id=run_id,
                        index=index,
                        track=track,
                        settings=settings,
                        parameters=parameters,
                        baseline_results=evidence,
                        initial_proposal=generated,
                        battle_memory=battle_memory,
                        incumbent=ai_incumbents.get(track),
                    )
                    candidate_futures[future] = (index, track)

                for future in as_completed(candidate_futures):
                    index, track = candidate_futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="failed",
                            error=f"{track} pipeline failed: {exc}",
                        )

            with self._lock:
                analysis_input = copy.deepcopy(self._runs[run_id])
            battle_analysis = build_battle_analysis(analysis_input)
            if self.educator is None:
                education_summary = battle_analysis.get("education_summary")
                if isinstance(education_summary, dict):
                    education_summary["llm_state"] = "fallback"
            self._change(
                run_id,
                state="completed",
                stage="Finished",
                battle_analysis=battle_analysis,
            )
            self._trace_change(run_id, state="completed", error=None)
            with self._lock:
                completed_run = copy.deepcopy(self._runs[run_id])
            round_result = (
                self.game_repository.complete_round(completed_run)
                if self.game_repository is not None
                else None
            )
            if round_result is not None and self._coach_executor is not None:
                self._coach_executor.submit(
                    self._generate_round_coaching,
                    run_id,
                    int(round_result["round_number"]),
                    battle_memory,
                )
            if self._education_executor is not None:
                self._education_executor.submit(
                    self._generate_education_review,
                    run_id,
                )
        except Exception as exc:
            self._change(
                run_id,
                state="failed",
                stage="Stopped",
                error=PUBLIC_FORGE_RUN_ERROR,
            )
            self._trace_change(run_id, state="failed", error=str(exc))
            if self.game_repository is not None:
                self.game_repository.fail_round(run_id, PUBLIC_FORGE_RUN_ERROR)
        finally:
            self._persist_history(run_id)
