from __future__ import annotations

import copy
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

from agent import (
    ACCEPTANCE_CHECK_IDS,
    DESIGNER_TRACKS,
    validate_candidate_source,
)
from app.schemas import GuidedHumanStrategy, HumanStrategyRequest, RunSettings
from app.services.acceptance_policy import normalize_acceptance_payload
from app.services.worker_client import LeanWorkerClient


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
MAX_REPAIR_ATTEMPTS = 3
MAX_MATCH_ROUNDS = 5
MAX_PUBLIC_CURVE_POINTS = 520


CRITICAL_LOG_MARKERS = (
    "Algorithm finished warming up.",
    "Firing On End Of Algorithm",
    "Algorithm Id:(UserStrategy) completed",
    "STATISTICS:: Total Orders ",
    "STATISTICS:: Start Equity ",
    "STATISTICS:: End Equity ",
    "STATISTICS:: Total Fees ",
    "STATISTICS:: Portfolio Turnover ",
    "DATA USAGE:: Failed data requests ",
)

AGENT_LOG_MARKERS = (
    "ERROR::",
    "Runtime Error",
    "PythonException",
    "Traceback",
    "Order Error:",
    " in main.py:",
    "Scheduled event:",
    "No method matches given arguments",
    "STATISTICS::",
    "DATA USAGE::",
)

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


def extract_critical_log_evidence(console_log: str) -> str:
    return "\n".join(
        line
        for line in console_log.splitlines()
        if any(marker in line for marker in CRITICAL_LOG_MARKERS)
    )


def compact_console_log(console_log: str, max_chars: int = 16_000) -> str:
    """Bound Agent context while keeping full logs in the persisted Worker attempt."""

    if max_chars < 1_000:
        raise ValueError("max_chars must be at least 1000")
    if len(console_log) <= max_chars:
        return console_log

    lines = console_log.splitlines()
    selected_indexes: set[int] = set()
    for index, line in enumerate(lines):
        if any(marker in line for marker in AGENT_LOG_MARKERS):
            selected_indexes.update(
                range(max(0, index - 2), min(len(lines), index + 3))
            )
    selected_indexes.update(range(min(20, len(lines))))
    selected_indexes.update(range(max(0, len(lines) - 80), len(lines)))
    excerpt = "\n".join(lines[index] for index in sorted(selected_indexes))

    header = (
        f"[AlphaForge compact LEAN log: original_chars={len(console_log)}, "
        f"selected_lines={len(selected_indexes)}]\n"
    )
    budget = max_chars - len(header)
    if len(excerpt) > budget:
        separator = "\n[... additional selected log text omitted ...]\n"
        head_chars = int((budget - len(separator)) * 0.55)
        tail_chars = budget - len(separator) - head_chars
        excerpt = excerpt[:head_chars] + separator + excerpt[-tail_chars:]
    return header + excerpt


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


def extract_error_log_excerpt(
    console_log: str,
    order_id: int | None = None,
) -> list[str]:
    lines = console_log.splitlines()
    selected: set[int] = set()
    order_markers = (
        (f"ids: [{order_id}]", f"Id: {order_id},")
        if order_id is not None
        else ()
    )
    for index, line in enumerate(lines):
        lowered = line.lower()
        matches_order = bool(order_markers) and any(
            marker in line for marker in order_markers
        )
        matches_error = order_id is None and (
            "error::" in lowered
            or "order error:" in lowered
            or "traceback (most recent call last)" in lowered
            or "unhandled exception" in lowered
        )
        if matches_order or matches_error:
            selected.update(range(max(0, index - 2), min(len(lines), index + 3)))
    return [lines[index] for index in sorted(selected)]


def build_runtime_failure_evidence(
    details: dict[str, Any] | None,
    console_log: str,
    *,
    details_error: str | None = None,
) -> dict[str, Any]:
    """Relate a failed order to the event, portfolio state, and exact log facts."""

    if not isinstance(details, dict):
        return {
            "details_available": False,
            "details_error": details_error or "alphaforge_details.json is unavailable",
            "failed_orders": [],
            "error_log_excerpt": extract_error_log_excerpt(console_log)[-120:],
        }

    orders = details.get("orders")
    events = details.get("order_events")
    snapshots = details.get("position_snapshots")
    orders = orders if isinstance(orders, list) else []
    events = events if isinstance(events, list) else []
    snapshots = snapshots if isinstance(snapshots, list) else []
    orders_by_id = {
        int(order["order_id"]): order
        for order in orders
        if isinstance(order, dict) and order.get("order_id") is not None
    }

    failed_orders: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("order_id") is None:
            continue
        status = str(event.get("status", "")).strip().upper().split(".")[-1]
        message = str(event.get("message") or "")
        if status not in {"INVALID", "REJECTED"} and not any(
            marker in message.lower()
            for marker in ("error", "insufficient", "failed", "rejected")
        ):
            continue
        order_id = int(event["order_id"])
        order = orders_by_id.get(order_id, {})
        event_time = str(event.get("time") or "")[:19]
        prior = [
            snapshot
            for snapshot in snapshots
            if isinstance(snapshot, dict)
            and str(snapshot.get("time") or "")[:19] <= event_time
        ]
        portfolio_before_failure = max(
            prior,
            key=lambda snapshot: str(snapshot.get("time") or "")[:19],
            default=None,
        )
        failed_orders.append(
            {
                "order": {
                    "order_id": order_id,
                    "symbol": order.get("symbol") or event.get("symbol"),
                    "quantity": order.get("quantity"),
                    "type": order.get("type"),
                    "status": order.get("status") or event.get("status"),
                    "submitted_at": order.get("time"),
                    "tag": order.get("tag"),
                    "price": order.get("price"),
                },
                "event": copy.deepcopy(event),
                "portfolio_before_failure": copy.deepcopy(
                    portfolio_before_failure
                ),
                "log_excerpt": extract_error_log_excerpt(console_log, order_id),
            }
        )
    return {
        "details_available": True,
        "details_error": None,
        "failed_orders": failed_orders,
        "failed_order_count": len(failed_orders),
        "evidence_truncated": False,
        "error_log_excerpt": extract_error_log_excerpt(console_log)[-120:],
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


def classify_candidate_failure(
    *,
    result: dict[str, Any],
    console_log: str,
    behavior_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map observed failures to stable repair categories before asking an Agent."""

    text = "\n".join(
        [
            str(result.get("status") or ""),
            " ".join(str(item) for item in result.get("errors", [])),
            console_log,
        ]
    ).lower()
    if (
        "no method matches given arguments for on" in text
        or "required by the on method" in text
    ):
        return {
            "code": "LEAN_SCHEDULE_SIGNATURE",
            "summary": (
                "ScheduleManager.on received an unsupported argument shape; pass "
                "the callback directly in the three- or four-argument overload."
            ),
        }
    if "af_record_ml_" in text and (
        "takes 2 positional arguments" in text
        or "unexpected keyword argument" in text
    ):
        return {
            "code": "ALPHAFORGE_EVIDENCE_SIGNATURE",
            "summary": (
                "An af_record_ml_* method was not called with its single dict payload."
            ),
        }
    patterns = (
        (
            "LEAN_SYMBOL_KEY",
            ("no key found for either mapped or original key", "keyerror"),
            "History or Slice access used a Symbol key that was not present.",
        ),
        (
            "XGBOOST_DMATRIX_API",
            ("dmatrix", "cannot unpack non-iterable dmatrix"),
            "The strategy used an unstable low-level XGBoost DMatrix path.",
        ),
        (
            "TRADEBARS_COLLECTION_API",
            ("tradebars", "has no attribute 'end_time'"),
            "The strategy treated a TradeBars collection as an individual TradeBar.",
        ),
        (
            "BUYING_POWER",
            ("insufficient buying power",),
            "Target exposure or order sequencing exceeded available buying power.",
        ),
        (
            "PYTHON_RUNTIME",
            ("runtime error", "pythonexception"),
            "LEAN raised a Python runtime exception.",
        ),
    )
    for code, markers, summary in patterns:
        if all(marker in text for marker in markers):
            return {"code": code, "summary": summary}

    evidence = behavior_evidence or {}
    if (
        result.get("status") == "completed"
        and int(evidence.get("ml_training_run_count") or 0) == 0
        and int(evidence.get("ml_prediction_count") or 0) > 0
    ):
        return {
            "code": "PREDICTIONS_WITHOUT_TRAINING",
            "summary": (
                "Predictions were recorded without a recorded training run. Inspect "
                "training-data row cardinality and early-return guards before changing "
                "the schedule, portfolio construction, or risk exposure."
            ),
        }
    if (
        result.get("status") == "completed"
        and int(evidence.get("filled_order_count") or 0) == 0
    ):
        if int(evidence.get("ml_training_run_count") or 0) == 0:
            code = "ZERO_ACTIVITY_NO_MODEL"
            summary = "The run completed with no fills and no recorded model training."
        elif int(evidence.get("ml_prediction_count") or 0) == 0:
            code = "ZERO_ACTIVITY_NO_PREDICTIONS"
            summary = "The model trained, but no recorded predictions reached selection."
        elif int(evidence.get("nonzero_target_event_count") or 0) == 0:
            code = "ZERO_ACTIVITY_NO_TARGETS"
            summary = "Predictions existed, but no non-zero target event was recorded."
        else:
            code = "ZERO_ACTIVITY_NO_ORDERS"
            summary = "Non-zero targets existed, but no order filled."
        return {"code": code, "summary": summary}
    return {
        "code": "UNCLASSIFIED",
        "summary": "Use the first concrete error or interrupted evidence stage.",
    }


def build_revision_effectiveness(
    *,
    previous: dict[str, Any] | None,
    summary: dict[str, Any],
    behavior_evidence: dict[str, Any],
    preflight: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    if previous is None:
        return {
            "kind": "initial_evaluation",
            "effective": True,
            "semantic_source_changed": None,
            "result_changed": None,
            "trading_behavior_changed": None,
            "resolved_checks": [],
            "remaining_failed_checks": [
                item["id"] for item in report["checks"] if item["status"] == "fail"
            ],
            "note": "First accepted-or-reviewed execution for this candidate.",
        }

    previous_report = previous.get("report") or {}
    previous_failed = {
        item.get("id")
        for item in previous_report.get("checks", [])
        if item.get("status") == "fail"
    }
    current_failed = {
        item.get("id")
        for item in report.get("checks", [])
        if item.get("status") == "fail"
    }
    resolved = sorted(previous_failed - current_failed)

    previous_preflight = previous.get("preflight") or {}
    semantic_changed = (
        preflight.get("semantic_sha256")
        != previous_preflight.get("semantic_sha256")
    )

    summary_keys = (
        "cagr",
        "sharpe_ratio",
        "maximum_drawdown",
        "end_equity",
    )
    result_changed = any(
        summary.get(key) != (previous.get("summary") or {}).get(key)
        for key in summary_keys
    )
    behavior_keys = (
        "filled_order_count",
        "invested_snapshot_count",
        "max_gross_exposure",
        "rebalance_count",
        "nonzero_target_event_count",
        "signal_event_count",
        "ml_training_run_count",
        "ml_prediction_count",
    )
    previous_behavior = previous.get("behavior_evidence") or {}
    behavior_changed = any(
        behavior_evidence.get(key) != previous_behavior.get(key)
        for key in behavior_keys
    )

    needs_execution_change = "A1" in previous_failed
    effective = bool(
        semantic_changed
        and resolved
        and (not needs_execution_change or behavior_changed or result_changed)
    )
    if not semantic_changed:
        kind = "ineffective"
        note = "Only comments or formatting changed; executable strategy logic did not."
    elif result_changed or behavior_changed:
        kind = "strategy_behavior_change"
        note = "Executable code and observed trading behavior or results changed."
    elif resolved:
        kind = "evidence_only"
        note = (
            "The revision improved audit evidence without changing trading results. "
            "Acceptance is not a profitability award."
        )
    else:
        kind = "ineffective"
        note = "Executable code changed, but no previously failed check was resolved."

    return {
        "kind": kind,
        "effective": effective,
        "semantic_source_changed": semantic_changed,
        "result_changed": result_changed,
        "trading_behavior_changed": behavior_changed,
        "resolved_checks": resolved,
        "remaining_failed_checks": sorted(current_failed),
        "note": note,
    }


def validate_acceptance_report(
    report: dict[str, Any],
    behavior_evidence: dict[str, Any],
    run_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = normalize_acceptance_payload(report)
    decision = report.get("decision")
    if decision not in {"accept", "revise"}:
        raise ValueError("acceptance decision must be accept or revise")
    checks = report.get("checks")
    if not isinstance(checks, list) or len(checks) != len(ACCEPTANCE_CHECK_IDS):
        raise ValueError("acceptance report must contain exactly checks A1 through A5")

    by_id: dict[str, dict[str, Any]] = {}
    for check in checks:
        if not isinstance(check, dict) or check.get("id") not in ACCEPTANCE_CHECK_IDS:
            raise ValueError("acceptance check id must be one of A1 through A5")
        check_id = str(check["id"])
        if check_id in by_id:
            raise ValueError(f"acceptance check {check_id} is duplicated")
        if check.get("status") not in {"pass", "fail"}:
            raise ValueError(f"acceptance check {check_id} must pass or fail")
        evidence = check.get("evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) and item.strip() for item in evidence)
        ):
            raise ValueError(f"acceptance check {check_id} needs concrete evidence")
        if not isinstance(check.get("reason"), str) or not check["reason"].strip():
            raise ValueError(f"acceptance check {check_id} needs a reason")
        by_id[check_id] = check
    if set(by_id) != set(ACCEPTANCE_CHECK_IDS):
        raise ValueError("acceptance report must contain exactly checks A1 through A5")

    activity_passes = (
        int(behavior_evidence.get("filled_order_count") or 0) > 0
        and int(behavior_evidence.get("invested_snapshot_count") or 0) > 0
        and float(behavior_evidence.get("max_gross_exposure") or 0) > 0
    )
    expected_a1 = "pass" if activity_passes else "fail"
    if by_id["A1"]["status"] != expected_a1:
        raise ValueError("acceptance check A1 contradicts behavior evidence")

    settings = run_settings or {}
    if settings:
        allowed_symbols = {
            str(symbol).strip().upper()
            for symbol in settings.get("symbols", [])
            if str(symbol).strip()
        }
        traded_symbols = {
            str(symbol).strip().upper()
            for symbol in behavior_evidence.get("traded_symbols", [])
            if str(symbol).strip()
        }
        benchmark = str(settings.get("benchmark") or "").strip().upper()
        unauthorized = traded_symbols - allowed_symbols
        benchmark_traded = bool(
            benchmark and benchmark in traded_symbols and benchmark not in allowed_symbols
        )
        expected_a5 = "fail" if unauthorized or benchmark_traded else "pass"
        if by_id["A5"]["status"] != expected_a5:
            raise ValueError("acceptance check A5 contradicts traded-symbol evidence")

    statuses = [by_id[check_id]["status"] for check_id in ACCEPTANCE_CHECK_IDS]
    repair_request = report.get("repair_request")
    if decision == "accept":
        if any(status != "pass" for status in statuses) or repair_request is not None:
            raise ValueError("accept requires all checks to pass and a null repair_request")
    elif (
        all(status == "pass" for status in statuses)
        or not isinstance(repair_request, str)
        or not repair_request.strip()
    ):
        raise ValueError("revise requires a failed check and a non-empty repair_request")
    return report


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
                "repair_attempts": 0,
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
            "repair_attempts": 0,
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
                "repair_attempts": int(item.get("repair_attempts") or 0),
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
        robustness = (
            0.6 * evidence_quality
            + 0.4 * max(0.4, 1.0 - 0.15 * entry["repair_attempts"])
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
        repairer: Any,
        acceptance_agent: Any,
        allowed_symbols: set[str],
        allowed_benchmarks: set[str],
        trace_root: Path | None = None,
        history_root: Path | None = None,
    ) -> None:
        self.worker = worker
        self.designer = designer
        self.repairer = repairer
        self.acceptance_agent = acceptance_agent
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
                "reason": "No AI candidate passed acceptance.",
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
            "schema_version": "1.1",
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
                    "repair_attempts": item.get("repair_attempts", 0),
                    "best_observed_attempt": item.get("best_observed_attempt"),
                    "design": copy.deepcopy(item.get("design")),
                    "repair_history": copy.deepcopy(
                        item.get("repair_history") or []
                    ),
                    "acceptance_history": copy.deepcopy(
                        item.get("acceptance_history") or []
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
                    "agent_capability_contract_v3",
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
            "validation_attempts": [],
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
    ) -> None:
        entry = {
            "track": track,
            "attempt": attempt,
            "worker_run_id": worker_run_id,
            "submitted_at": utc_now(),
            "finished_at": None,
            "source_code": source_code,
            "parameters": copy.deepcopy(parameters),
            "result": None,
            "console_log": None,
            "behavior_evidence": None,
            "runtime_failure_evidence": None,
            "acceptance_report": None,
            "outcome": "running",
            "error": None,
        }
        with self._lock:
            self._traces[run_id]["worker_attempts"].append(entry)
            self._traces[run_id]["updated_at"] = utc_now()
            self._persist_trace_locked(run_id)

    def _record_validation_attempt(
        self,
        *,
        run_id: str,
        track: str,
        attempt: int,
        report: dict[str, Any],
    ) -> None:
        entry = {
            "track": track,
            "attempt": attempt,
            "validated_at": utc_now(),
            "report": copy.deepcopy(report),
        }
        with self._lock:
            self._traces[run_id]["validation_attempts"].append(entry)
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
                    "summary": {},
                    "analysis": {},
                    "behavior_evidence": {},
                    "error": None,
                    "usage": {},
                    "generation_retries": 0,
                    "repair_attempts": 0,
                    "preflight": None,
                    "validation_history": [],
                    "repair_history": [],
                    "acceptance": None,
                    "acceptance_history": [],
                    "best_observed_attempt": None,
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
        while True:
            record = self.worker.job(worker_run_id)
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

    def _run_candidate(
        self,
        *,
        run_id: str,
        index: int,
        track: str,
        settings: RunSettings,
        parameters: dict[str, str],
        baseline_results: list[dict[str, Any]],
        generated: dict[str, Any],
    ) -> None:
        source_code = generated["source_code"]
        design = generated.get("design")
        usage = self._add_usage({}, generated.get("usage", {}))
        validation_history: list[dict[str, Any]] = []
        repair_history: list[dict[str, Any]] = []
        self._change_item(
            run_id,
            "candidates",
            index,
            state="submitting",
            source_code=source_code,
            design=design,
            usage=usage,
            repair_attempts=0,
            preflight=None,
            validation_history=[],
            repair_history=[],
            error=None,
        )

        acceptance_history: list[dict[str, Any]] = []
        best_observed: dict[str, Any] | None = None

        def restore_best_observed(error: str) -> bool:
            if best_observed is None:
                return False
            self._change_item(
                run_id,
                "candidates",
                index,
                state="rejected",
                worker_run_id=best_observed["worker_run_id"],
                source_code=best_observed["source_code"],
                summary=copy.deepcopy(best_observed["summary"]),
                analysis=copy.deepcopy(best_observed["analysis"]),
                behavior_evidence=copy.deepcopy(
                    best_observed["behavior_evidence"]
                ),
                preflight=copy.deepcopy(best_observed["preflight"]),
                acceptance=copy.deepcopy(best_observed["acceptance"]),
                best_observed_attempt=best_observed["attempt"],
                error=error,
            )
            return True

        for repair_attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            preflight = validate_candidate_source(source_code, track)
            validation_history.append(
                {
                    "attempt": repair_attempt,
                    **copy.deepcopy(preflight),
                }
            )
            self._record_validation_attempt(
                run_id=run_id,
                track=track,
                attempt=repair_attempt,
                report=preflight,
            )
            self._change_item(
                run_id,
                "candidates",
                index,
                preflight=preflight,
                validation_history=copy.deepcopy(validation_history),
            )
            if preflight["status"] != "passed":
                messages = [
                    f"{item['code']}: {item['message']}"
                    for item in preflight["diagnostics"]
                ]
                repair_reason = "; ".join(messages)
                if repair_attempt == MAX_REPAIR_ATTEMPTS:
                    if not restore_best_observed(repair_reason):
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="failed",
                            error=repair_reason,
                        )
                    return
                next_attempt = repair_attempt + 1
                self._change(
                    run_id,
                    stage=(
                        f"Repairing {track} candidate static validation "
                        f"· attempt {next_attempt}"
                    ),
                )
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="repairing",
                    repair_attempts=next_attempt,
                    error=repair_reason,
                )
                try:
                    repaired = self.repairer.repair(
                        track=track,
                        run_settings=settings.model_dump(mode="json"),
                        baseline_results=baseline_results,
                        source_code=source_code,
                        worker_result={
                            "status": "static_validation_failed",
                            "errors": messages,
                        },
                        lean_console_log=repair_reason,
                        repair_attempt=next_attempt,
                        repair_trigger="static_validation",
                        acceptance_report=None,
                        validation_report=preflight,
                        candidate_design=design,
                    )
                    self._record_agent_call(
                        run_id=run_id,
                        track=track,
                        stage="repair",
                        attempt=next_attempt,
                        trace=repaired.get("trace"),
                    )
                except Exception as exc:
                    self._record_agent_call(
                        run_id=run_id,
                        track=track,
                        stage="repair",
                        attempt=next_attempt,
                        trace=getattr(exc, "trace", None),
                        error=exc,
                    )
                    if restore_best_observed(
                        f"Repair Agent failed after a runnable attempt: {exc}"
                    ):
                        return
                    raise
                source_code = repaired["source_code"]
                usage = self._add_usage(usage, repaired.get("usage", {}))
                repair_history.append(
                    {
                        "attempt": next_attempt,
                        "trigger": "static_validation",
                        "classification": "STATIC_VALIDATION",
                        "change_summary": repaired.get("change_summary", []),
                        "first_interrupted_stage": repaired.get(
                            "first_interrupted_stage"
                        ),
                    }
                )
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    state="submitting",
                    source_code=source_code,
                    usage=usage,
                    repair_history=copy.deepcopy(repair_history),
                    error=None,
                )
                continue

            submitted = self.worker.submit_custom(source_code, parameters)
            worker_run_id = submitted["run_id"]
            self._record_worker_attempt(
                run_id=run_id,
                track=track,
                attempt=repair_attempt,
                worker_run_id=worker_run_id,
                source_code=source_code,
                parameters=parameters,
            )
            try:
                result = self._wait_for_worker(
                    run_id,
                    "candidates",
                    index,
                    worker_run_id,
                )
            except Exception as exc:
                result = {"status": "failed", "summary": {}, "errors": [str(exc)]}

            if result.get("status") == "completed":
                self._change(
                    run_id,
                    stage=f"Validating {track} candidate · attempt {len(acceptance_history) + 1}",
                )
                self._change_item(run_id, "candidates", index, state="validating")
                try:
                    console_log = self.worker.log(worker_run_id)
                    behavior_evidence = build_behavior_evidence(
                        self.worker.details(worker_run_id)
                    )
                    acceptance_console_log = compact_console_log(
                        console_log,
                        max_chars=12_000,
                    )
                except Exception as exc:
                    self._update_worker_attempt(
                        run_id=run_id,
                        worker_run_id=worker_run_id,
                        finished_at=utc_now(),
                        result=result,
                        outcome="evidence_failed",
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                    raise
                self._update_worker_attempt(
                    run_id=run_id,
                    worker_run_id=worker_run_id,
                    finished_at=utc_now(),
                    result=result,
                    console_log=console_log,
                    behavior_evidence=behavior_evidence,
                    outcome="awaiting_acceptance",
                    error=None,
                )
                acceptance_attempt = len(acceptance_history) + 1
                try:
                    evaluated = self.acceptance_agent.evaluate(
                        track=track,
                        run_settings=settings.model_dump(mode="json"),
                        critical_log_evidence=extract_critical_log_evidence(console_log),
                        source_code=source_code,
                        worker_result=result,
                        lean_console_log=acceptance_console_log,
                        behavior_evidence=behavior_evidence,
                        acceptance_attempt=acceptance_attempt,
                        candidate_design=design,
                        preflight_report=preflight,
                        previous_acceptance=(
                            acceptance_history[-1]
                            if acceptance_history
                            else None
                        ),
                    )
                    self._record_agent_call(
                        run_id=run_id,
                        track=track,
                        stage="acceptance",
                        attempt=acceptance_attempt,
                        trace=evaluated.get("trace"),
                    )
                except Exception as exc:
                    self._record_agent_call(
                        run_id=run_id,
                        track=track,
                        stage="acceptance",
                        attempt=acceptance_attempt,
                        trace=getattr(exc, "trace", None),
                        error=exc,
                    )
                    self._update_worker_attempt(
                        run_id=run_id,
                        worker_run_id=worker_run_id,
                        outcome="acceptance_call_failed",
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                    raise
                usage = self._add_usage(usage, evaluated.get("usage", {}))
                self._change_item(run_id, "candidates", index, usage=usage)
                try:
                    agent_report = normalize_acceptance_payload(
                        evaluated.get("report", {})
                    )
                    report = validate_acceptance_report(
                        agent_report,
                        behavior_evidence=behavior_evidence,
                        run_settings=settings.model_dump(mode="json"),
                    )
                except Exception as exc:
                    self._update_worker_attempt(
                        run_id=run_id,
                        worker_run_id=worker_run_id,
                        outcome="acceptance_response_invalid",
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                    raise
                previous_acceptance = (
                    acceptance_history[-1] if acceptance_history else None
                )
                revision_effectiveness = build_revision_effectiveness(
                    previous=previous_acceptance,
                    summary=result.get("summary", {}),
                    behavior_evidence=behavior_evidence,
                    preflight=preflight,
                    report=report,
                )
                acceptance_history.append(
                    {
                        "attempt": len(acceptance_history) + 1,
                        "worker_run_id": worker_run_id,
                        "summary": copy.deepcopy(result.get("summary", {})),
                        "behavior_evidence": behavior_evidence,
                        "preflight": preflight,
                        "report": report,
                        "agent_report": agent_report,
                        "revision_effectiveness": revision_effectiveness,
                        "source_code": source_code,
                        "usage": evaluated.get("usage", {}),
                    }
                )
                self._change_item(
                    run_id,
                    "candidates",
                    index,
                    acceptance=report,
                    acceptance_history=copy.deepcopy(acceptance_history),
                    usage=usage,
                )
                if int(behavior_evidence.get("filled_order_count") or 0) > 0:
                    with self._lock:
                        candidate_snapshot = copy.deepcopy(
                            self._runs[run_id]["candidates"][index]
                        )
                    observed = {
                        "attempt": repair_attempt,
                        "worker_run_id": worker_run_id,
                        "source_code": source_code,
                        "summary": copy.deepcopy(result.get("summary", {})),
                        "analysis": candidate_snapshot.get("analysis", {}),
                        "behavior_evidence": behavior_evidence,
                        "preflight": preflight,
                        "acceptance": report,
                    }
                    if (
                        best_observed is None
                        or self._entry_score(observed["summary"])
                        > self._entry_score(best_observed["summary"])
                    ):
                        best_observed = observed
                if report["decision"] == "accept":
                    self._update_worker_attempt(
                        run_id=run_id,
                        worker_run_id=worker_run_id,
                        acceptance_report=report,
                        outcome="accepted",
                    )
                    self._change_item(
                        run_id,
                        "candidates",
                        index,
                        state="accepted",
                        error=None,
                    )
                    return
                self._update_worker_attempt(
                    run_id=run_id,
                    worker_run_id=worker_run_id,
                    acceptance_report=report,
                    outcome="acceptance_revision",
                )
                if repair_attempt == MAX_REPAIR_ATTEMPTS:
                    if not restore_best_observed(report["repair_request"]):
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="rejected",
                            error=report["repair_request"],
                        )
                    return
                repair_trigger = "acceptance_revision"
                acceptance_report = report
                repair_reason = report["repair_request"]
                diagnostic_report = {
                    "preflight": preflight,
                    "failure_classification": classify_candidate_failure(
                        result=result,
                        console_log=console_log,
                        behavior_evidence=behavior_evidence,
                    ),
                    "behavior_evidence": behavior_evidence,
                    "failed_checks": [
                        check["id"]
                        for check in report["checks"]
                        if check["status"] == "fail"
                    ],
                }
            else:
                try:
                    console_log = self.worker.log(worker_run_id)
                except Exception:
                    console_log = "\n".join(result.get("errors", []))
                try:
                    failure_details = self.worker.details(worker_run_id)
                    details_error = None
                except Exception as exc:
                    failure_details = None
                    details_error = f"{type(exc).__name__}: {exc}"
                runtime_failure_evidence = build_runtime_failure_evidence(
                    failure_details,
                    console_log,
                    details_error=details_error,
                )
                repair_reason = (
                    "; ".join(result.get("errors", [])) or "LEAN run failed"
                )
                self._update_worker_attempt(
                    run_id=run_id,
                    worker_run_id=worker_run_id,
                    finished_at=utc_now(),
                    result=result,
                    console_log=console_log,
                    runtime_failure_evidence=runtime_failure_evidence,
                    outcome="runtime_failure",
                    error={"type": "worker_failure", "message": repair_reason},
                )
                if repair_attempt == MAX_REPAIR_ATTEMPTS:
                    terminal_error = (
                        "; ".join(result.get("errors", []))
                        or "LEAN run failed"
                    )
                    if not restore_best_observed(terminal_error):
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="failed",
                            error=terminal_error,
                        )
                    return
                repair_trigger = "runtime_failure"
                acceptance_report = None
                diagnostic_report = {
                    "preflight": preflight,
                    "failure_classification": classify_candidate_failure(
                        result=result,
                        console_log=console_log,
                    ),
                    "runtime_failure_evidence": runtime_failure_evidence,
                }

            next_attempt = repair_attempt + 1
            self._change(
                run_id,
                stage=f"Repairing {track} candidate · attempt {next_attempt}",
            )
            self._change_item(
                run_id,
                "candidates",
                index,
                state="repairing",
                repair_attempts=next_attempt,
                error=repair_reason,
            )
            try:
                repaired = self.repairer.repair(
                    track=track,
                    run_settings=settings.model_dump(mode="json"),
                    baseline_results=baseline_results,
                    source_code=source_code,
                    worker_result=result,
                    lean_console_log=console_log,
                    repair_attempt=next_attempt,
                    repair_trigger=repair_trigger,
                    acceptance_report=acceptance_report,
                    validation_report=diagnostic_report,
                    candidate_design=design,
                )
                self._record_agent_call(
                    run_id=run_id,
                    track=track,
                    stage="repair",
                    attempt=next_attempt,
                    trace=repaired.get("trace"),
                )
            except Exception as exc:
                self._record_agent_call(
                    run_id=run_id,
                    track=track,
                    stage="repair",
                    attempt=next_attempt,
                    trace=getattr(exc, "trace", None),
                    error=exc,
                )
                if restore_best_observed(
                    f"Repair Agent failed after a runnable attempt: {exc}"
                ):
                    return
                raise
            source_code = repaired["source_code"]
            usage = self._add_usage(usage, repaired.get("usage", {}))
            repair_history.append(
                {
                    "attempt": next_attempt,
                    "trigger": repair_trigger,
                    "classification": diagnostic_report[
                        "failure_classification"
                    ]["code"],
                    "change_summary": repaired.get("change_summary", []),
                    "first_interrupted_stage": repaired.get(
                        "first_interrupted_stage"
                    ),
                }
            )
            self._change_item(
                run_id,
                "candidates",
                index,
                state="submitting",
                source_code=source_code,
                usage=usage,
                repair_history=copy.deepcopy(repair_history),
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
                            attempt=0,
                            trace=generated.get("trace"),
                        )
                        generated_candidates[index] = generated
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="generated",
                            source_code=generated["source_code"],
                            design=generated.get("design"),
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
                            attempt=0,
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
                    self._run_candidate(
                        run_id=run_id,
                        index=index,
                        track=track,
                        settings=settings,
                        parameters=parameters,
                        baseline_results=evidence,
                        generated=generated,
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
