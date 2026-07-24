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
    """Build the complete LEAN source for the small guided Human form."""

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
        risk_adjusted = (
            0.65 * _normalized(sharpe, metric_values["sharpe_ratio"])
            + 0.35 * _normalized(cagr, metric_values["cagr"])
        )
        drawdown_control = (
            0.65
            * _normalized(
                drawdown,
                metric_values["maximum_drawdown"],
                lower_is_better=True,
            )
            + 0.35
            * _normalized(
                volatility,
                metric_values["annualized_volatility"],
                lower_is_better=True,
            )
        )
        evidence = entry["behavior_evidence"]
        evidence_quality = statistics.fmean(
            [
                1.0 if int(evidence.get("filled_order_count") or 0) > 0 else 0.0,
                1.0 if int(evidence.get("invested_snapshot_count") or 0) > 0 else 0.0,
                1.0 if float(evidence.get("max_gross_exposure") or 0) > 0 else 0.0,
            ]
        )
        robustness = evidence_quality
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
            "risk_adjusted_return": round(risk_adjusted * 100, 2),
            "drawdown_and_volatility": round(drawdown_control * 100, 2),
            "robustness": round(robustness * 100, 2),
            "cost_and_turnover": round(cost * 100, 2),
            "explainability": round(float(entry["explainability"]) * 100, 2),
        }
        score = (
            components["risk_adjusted_return"] * 0.40
            + components["drawdown_and_volatility"] * 0.25
            + components["robustness"] * 0.20
            + components["cost_and_turnover"] * 0.10
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
        if abs(gap) <= 2.0:
            verdict = {
                "side": "draw",
                "label": "Draw",
                "reason": "Composite scores are within the public two-point draw band.",
                "score_gap": gap,
            }
        elif gap > 0:
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
                "Risk-adjusted return is at least as strong as the AI champion."
            )
        else:
            improvements.append(
                "Improve signal quality or volatility targeting; Human Sharpe trails the AI champion."
            )
        if human_dd <= ai_dd:
            strengths.append(
                "Drawdown control is at least as strong as the AI champion."
            )
        else:
            improvements.append(
                "Add a portfolio risk budget, defensive regime rule, or smaller position cap to reduce drawdown."
            )
        if (
            human_turnover is not None
            and ai_turnover is not None
            and human_turnover > ai_turnover * 1.15
        ):
            improvements.append(
                "Reduce unnecessary turnover with a slower rebalance schedule or a no-trade band."
            )
    else:
        strengths.append("The Human strategy is the only eligible contestant.")
    if len(improvements) < 2:
        improvements.append(
            "Stress-test the lookback and holding count instead of optimizing one point estimate."
        )
    if len(improvements) < 3:
        improvements.append(
            "Reserve a later time window for a blind check before treating the next revision as an improvement."
        )

    return {
        "schema_version": "1.0",
        "judge": {
            "method": "deterministic_weighted_score_v1",
            "weights": {
                "risk_adjusted_return": 0.40,
                "drawdown_and_volatility": 0.25,
                "robustness": 0.20,
                "cost_and_turnover": 0.10,
                "explainability": 0.05,
            },
            "draw_band_points": 2.0,
            "scorecards": scorecards,
        },
        "ai_champion": copy.deepcopy(ai_champion),
        "reference_leader": copy.deepcopy(reference_leader),
        "overall_best": copy.deepcopy(overall_best),
        "verdict": verdict,
        "education_summary": {
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
            },
            "knowledge_card": {
                "title": "Return is not the same as risk-adjusted return",
                "lesson": (
                    "CAGR measures growth, Sharpe relates excess return to volatility, "
                    "and drawdown measures loss from a peak. A stronger strategy balances "
                    "all three rather than maximizing one."
                ),
                "question": (
                    "Would you still choose the highest-CAGR strategy if it required a "
                    "materially larger drawdown and more trading?"
                ),
            },
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
    """Score deterministic stress runs without asking an LLM to judge itself."""

    primary_cagr = _number(primary_summary.get("cagr"), 0.0)
    primary_sharpe = _number(primary_summary.get("sharpe_ratio"), 0.0)
    primary_drawdown = _number(
        primary_summary.get("maximum_drawdown"),
        0.0,
    )
    evaluated = [item for item in scenarios if item.get("state") != "skipped"]
    passed_checks = 0
    total_checks = 0
    completed_count = 0
    for scenario in evaluated:
        summary = scenario.get("summary") or {}
        behavior = scenario.get("behavior_evidence") or {}
        completed = scenario.get("state") == "completed"
        if completed:
            completed_count += 1
        cagr = _number(summary.get("cagr"), 0.0)
        sharpe = _number(summary.get("sharpe_ratio"), 0.0)
        drawdown = _number(summary.get("maximum_drawdown"), 0.0)
        cagr_floor = (
            primary_cagr
            * (0.70 if scenario.get("id") == "friction_2x" else 0.35)
            if primary_cagr > 0
            else 0.0
        )
        drawdown_ceiling = min(0.60, max(0.35, primary_drawdown + 0.15))
        checks = [
            {
                "id": "completed",
                "passed": completed,
                "observed": scenario.get("state"),
                "threshold": "completed",
            },
            {
                "id": "active",
                "passed": (
                    completed
                    and int(behavior.get("filled_order_count") or 0) > 0
                    and float(behavior.get("max_gross_exposure") or 0) > 0
                ),
                "observed": int(behavior.get("filled_order_count") or 0),
                "threshold": "filled orders > 0",
            },
            {
                "id": "return_retention",
                "passed": completed and cagr >= cagr_floor,
                "observed": cagr,
                "threshold": cagr_floor,
            },
            {
                "id": "risk_control",
                "passed": (
                    completed
                    and sharpe > 0
                    and drawdown <= drawdown_ceiling
                ),
                "observed": {
                    "sharpe_ratio": sharpe,
                    "maximum_drawdown": drawdown,
                },
                "threshold": {
                    "sharpe_ratio": "> 0",
                    "maximum_drawdown": drawdown_ceiling,
                },
            },
        ]
        scenario["checks"] = checks
        scenario["cagr_retention"] = (
            cagr / primary_cagr if primary_cagr > 0 else None
        )
        scenario["sharpe_retention"] = (
            sharpe / primary_sharpe if primary_sharpe > 0 else None
        )
        scenario["drawdown_change"] = drawdown - primary_drawdown
        passed_checks += sum(1 for check in checks if check["passed"])
        total_checks += len(checks)

    score = round(100 * passed_checks / total_checks, 1) if total_checks else 0.0
    if len(evaluated) < 3 or completed_count < 2:
        grade = "insufficient"
        conclusion = "Not enough completed stress scenarios for a robustness conclusion."
    elif score >= 75:
        grade = "robust"
        conclusion = "The strategy retained activity, return, and risk control across most stresses."
    elif score >= 50:
        grade = "mixed"
        conclusion = "The strategy survived some stresses but remains sensitive to at least one regime or assumption."
    else:
        grade = "fragile"
        conclusion = "The strategy materially deteriorated under the deterministic stress battery."
    return {
        "policy_version": "deterministic-robustness-v1",
        "score": score,
        "grade": grade,
        "conclusion": conclusion,
        "completed_scenarios": completed_count,
        "evaluated_scenarios": len(evaluated),
        "limitations": [
            "These are repeated historical simulations, not proof of future performance.",
            "The recent-regime slice is pseudo-out-of-sample because the design process saw full-period public baseline evidence.",
            "Parameter sweeps are intentionally excluded to reduce backtest overfitting.",
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
    ) -> None:
        self.worker = worker
        self.designer = designer
        self.critic = critic
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
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge")

    def _trace_path(self, run_id: str) -> Path:
        if self.trace_root is None:
            raise RuntimeError("Agent trace persistence is not configured")
        if not run_id.startswith("forge-") or not run_id[6:].isalnum():
            raise ValueError("invalid Forge run_id")
        return self.trace_root / f"{run_id}.json"

    def _history_path(self, run_id: str) -> Path:
        if self.history_root is None:
            raise RuntimeError("Forge history persistence is not configured")
        if not run_id.startswith("forge-") or not run_id[6:].isalnum():
            raise ValueError("invalid Forge run_id")
        return self.history_root / f"{run_id}.json"

    @staticmethod
    def _entry_score(summary: dict[str, Any]) -> tuple[float, float, float]:
        def metric(name: str, default: float) -> float:
            value = summary.get(name)
            return default if value is None else float(value)

        return (
            metric("sharpe_ratio", float("-inf")),
            metric("cagr", float("-inf")),
            -metric("maximum_drawdown", float("inf")),
        )

    def _history_record(self, run: dict[str, Any]) -> dict[str, Any]:
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
        with self._lock:
            run = copy.deepcopy(self._runs[run_id])
        record = self._history_record(run)
        with self._history_lock:
            path = self._history_path(run_id)
            temporary = path.with_suffix(f".{threading.get_ident()}.json.tmp")
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)

            def created_at(history_path: Path) -> str:
                try:
                    return str(
                        json.loads(history_path.read_text(encoding="utf-8")).get(
                            "created_at",
                            "",
                        )
                    )
                except (OSError, json.JSONDecodeError):
                    return ""

            history_files = sorted(
                self.history_root.glob("forge-*.json"),
                key=created_at,
                reverse=True,
            )
            for stale_path in history_files[MAX_MATCH_ROUNDS:]:
                stale_path.unlink(missing_ok=True)

    def list_history(self, limit: int = MAX_MATCH_ROUNDS) -> list[dict[str, Any]]:
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
        return records[: max(0, min(limit, MAX_MATCH_ROUNDS))]

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
    ) -> dict[str, Any]:
        unknown = sorted(set(settings.symbols).difference(self.allowed_symbols))
        if unknown:
            raise ValueError(f"stocks are not available in the local dataset: {unknown}")
        if settings.benchmark not in self.allowed_benchmarks:
            raise ValueError(
                f"benchmark must be one of {sorted(self.allowed_benchmarks)}"
            )

        run_id = f"forge-{uuid.uuid4().hex[:12]}"
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
                    "usage": {},
                    "generation_retries": 0,
                    "iteration_count": 0,
                    "best_iteration": None,
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
        }
        self._initialize_trace(run_id=run_id, settings=settings)
        with self._lock:
            self._runs[run_id] = run
        self._executor.submit(self._execute, run_id, settings, human_source)
        return copy.deepcopy(run)

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            result = copy.deepcopy(run) if run is not None else None
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
            self._change(
                run_id,
                stage=(
                    f"Running {track} parameters · iteration "
                    f"{iteration_number}/{MAX_TEMPLATE_BACKTESTS}"
                ),
            )
            try:
                validated = validate_strategy_spec(proposal["strategy_spec"])
                spec = validated.model_dump(mode="json")
                source = compile_strategy_source(validated)
            except Exception as exc:
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="failed",
                    error=f"Template parameter contract failed: {exc}",
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
                partial_completion_reason = str(exc)
                if worker_run_id is not None:
                    self._update_worker_attempt(
                        run_id=run_id,
                        worker_run_id=worker_run_id,
                        finished_at=utc_now(),
                        outcome="worker_polling_failed",
                        error={
                            "type": type(exc).__name__,
                            "message": partial_completion_reason,
                        },
                    )
                if iterations:
                    break
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="failed",
                    error=str(exc),
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
                partial_completion_reason = message
                if iterations:
                    break
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="failed",
                    error=message,
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
                iterations[-1]["critique_error"] = str(exc)
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
                iterations[-1]["revision_error"] = str(exc)
                break

        if not iterations:
            self._change_item(
                run_id,
                "candidates",
                index,
                state="failed",
                error="No parameter iteration completed",
                failure_classification="agent_or_platform_failure",
            )
            return

        best = max(iterations, key=lambda item: tuple(item["selection_key"]))
        self._change_item(
            run_id,
            "candidates",
            index,
            state="accepted",
            worker_run_id=best["worker_run_id"],
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
            best_iteration=best["iteration"],
            iterations=copy.deepcopy(iterations),
            critique_history=copy.deepcopy(critiques),
            attempted_iteration_count=attempted_iteration_count,
            partial_completion=attempted_iteration_count > len(iterations),
            partial_completion_reason=partial_completion_reason,
            failure_classification=None,
            error=None,
        )

    def _execute(
        self,
        run_id: str,
        settings: RunSettings,
        human_source: str,
    ) -> None:
        parameters = settings.worker_parameters()
        try:
            self._change(run_id, state="running", stage="Running four public baselines")
            evidence: list[dict[str, Any]] = []
            for index, baseline in enumerate(BASELINES):
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
                evidence.append(
                    {
                        "name": baseline["name"],
                        "family": baseline["family"],
                        "summary": result.get("summary", {}),
                        "performance_profile": copy.deepcopy(
                            self._runs[run_id]["baselines"][index]
                            .get("analysis", {})
                            .get("statistics", {})
                        ),
                        "execution_profile": {
                            key: self._runs[run_id]["baselines"][index]
                            .get("behavior_evidence", {})
                            .get(key)
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
                )

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
                    )
                    future = designer_executor.submit(
                        self.designer.generate,
                        track=track,
                        run_settings=settings.model_dump(mode="json"),
                        baseline_results=evidence,
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
                        )
                    except Exception as exc:
                        failed_trace = getattr(exc, "trace", None)
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
                            error=str(exc),
                        )

            for index, track in enumerate(DESIGNER_TRACKS):
                generated = generated_candidates.get(index)
                if generated is None:
                    continue
                self._change(
                    run_id,
                    stage=f"Running {track} Designer candidate",
                )
                try:
                    self._run_template_candidate(
                        run_id=run_id,
                        index=index,
                        track=track,
                        settings=settings,
                        parameters=parameters,
                        baseline_results=evidence,
                        initial_proposal=generated,
                    )
                except Exception as exc:
                    self._change_item(
                        run_id,
                        "candidates",
                        index,
                        state="failed",
                        error=str(exc),
                    )

            with self._lock:
                analysis_input = copy.deepcopy(self._runs[run_id])
            battle_analysis = build_battle_analysis(analysis_input)
            self._change(
                run_id,
                state="completed",
                stage="Finished",
                battle_analysis=battle_analysis,
            )
            self._trace_change(run_id, state="completed", error=None)
        except Exception as exc:
            self._change(run_id, state="failed", stage="Stopped", error=str(exc))
            self._trace_change(run_id, state="failed", error=str(exc))
        finally:
            self._persist_history(run_id)
