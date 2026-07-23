from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import (
    ACCEPTANCE_CHECK_IDS,
    DESIGNER_TRACKS,
    validate_candidate_source,
)
from app.schemas import GuidedHumanStrategy, HumanStrategyRequest, RunSettings
from app.services.acceptance_policy import (
    build_deterministic_acceptance_report,
    normalize_acceptance_payload,
)
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
    " in main.py:",
    "Scheduled event:",
    "No method matches given arguments",
    "STATISTICS::",
    "DATA USAGE::",
)


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
        "traded_symbols": traded_symbols,
        "first_fill_time": fill_times[0] if fill_times else None,
        "last_fill_time": fill_times[-1] if fill_times else None,
        "position_snapshot_count": len(snapshots),
        "invested_snapshot_count": len(invested_snapshots),
        "max_gross_exposure": max_gross_exposure,
        "rebalance_count": len(rebalances),
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

    def initialize_strategy(self):
        start = datetime.fromisoformat(self._parameter("start_date", "2020-01-02"))
        end = datetime.fromisoformat(self._parameter("end_date", "2024-12-31"))
        self.set_start_date(start.year, start.month, start.day)
        self.set_end_date(end.year, end.month, end.day)
        self.set_cash(float(self._parameter("initial_cash", "100000")))
        self.target_gross = 0.95
        self.lookback_days = {strategy.lookback_days}
        self.holdings = {strategy.holdings}

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

    def rebalance(self):
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
            self.af_rebalance_to_weights({{}}, "No valid {signal_label.lower()} signals")
            return
        weight = self.target_gross / len(selected)
        targets = {{symbol: weight for symbol in selected}}
        self.af_rebalance_to_weights(targets, "Guided Human · {signal_label}")

    def on_alpha_data(self, data):
        pass
'''


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

        return {
            "schema_version": "1.0",
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
                    "repair_attempts": item.get("repair_attempts", 0),
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
            "best_ai_track": best_ai.get("track") if best_ai else None,
        }

    def _persist_history(self, run_id: str) -> None:
        if self.history_root is None:
            return
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
                    "agent_capability_contract_v2",
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
                    "error": None,
                    "usage": {},
                    "repair_attempts": 0,
                    "preflight": None,
                    "validation_history": [],
                    "repair_history": [],
                    "acceptance": None,
                    "acceptance_history": [],
                }
                for track in DESIGNER_TRACKS
            ],
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "error": None,
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
            self._change_item(
                run_id,
                collection,
                index,
                state=result.get("status", state),
                summary=result.get("summary", {}),
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
        if completed:
            try:
                behavior_evidence = build_behavior_evidence(
                    self.worker.details(worker_run_id)
                )
            except Exception:
                behavior_evidence = {}
        self._change_human(
            run_id,
            state=result.get("status", state),
            summary=result.get("summary", {}),
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
                    advisory_report = normalize_acceptance_payload(
                        evaluated.get("report", {})
                    )
                    report = build_deterministic_acceptance_report(
                        track=track,
                        run_settings=settings.model_dump(mode="json"),
                        worker_result=result,
                        behavior_evidence=behavior_evidence,
                        preflight_report=preflight,
                        advisory_payload=advisory_report,
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
                if (
                    report["decision"] == "accept"
                    and previous_acceptance is not None
                    and not revision_effectiveness["effective"]
                ):
                    report = copy.deepcopy(report)
                    deterministic_check = next(
                        item for item in report["checks"] if item["id"] == "A2"
                    )
                    deterministic_check["status"] = "fail"
                    deterministic_check["evidence"] = [
                        revision_effectiveness["note"],
                        "semantic_source_changed="
                        + str(
                            revision_effectiveness["semantic_source_changed"]
                        ).lower(),
                        "trading_behavior_changed="
                        + str(
                            revision_effectiveness["trading_behavior_changed"]
                        ).lower(),
                    ]
                    deterministic_check["reason"] = (
                        "A claimed repair must materially change executable code and "
                        "resolve an observed failed stage."
                    )
                    report["decision"] = "revise"
                    report["repair_request"] = (
                        "The last revision was deterministically ineffective. Change "
                        "the executable logic or structured evidence that caused the "
                        "previous failed check; comments and formatting do not count."
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
                        "agent_advisory": advisory_report,
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
                repair_reason = (
                    "; ".join(result.get("errors", [])) or "LEAN run failed"
                )
                self._update_worker_attempt(
                    run_id=run_id,
                    worker_run_id=worker_run_id,
                    finished_at=utc_now(),
                    result=result,
                    console_log=console_log,
                    outcome="runtime_failure",
                    error={"type": "worker_failure", "message": repair_reason},
                )
                if repair_attempt == MAX_REPAIR_ATTEMPTS:
                    self._change_item(
                        run_id,
                        "candidates",
                        index,
                        state="failed",
                        error="; ".join(result.get("errors", [])) or "LEAN run failed",
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
                    lean_console_log=compact_console_log(
                        console_log,
                        max_chars=20_000,
                    ),
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
                    }
                )

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
                            error=None,
                        )
                    except Exception as exc:
                        self._record_agent_call(
                            run_id=run_id,
                            track=track,
                            stage="designer",
                            attempt=0,
                            trace=getattr(exc, "trace", None),
                            error=exc,
                        )
                        self._change_item(
                            run_id,
                            "candidates",
                            index,
                            state="failed",
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

            self._change(run_id, state="completed", stage="Finished")
            self._trace_change(run_id, state="completed", error=None)
        except Exception as exc:
            self._change(run_id, state="failed", stage="Stopped", error=str(exc))
            self._trace_change(run_id, state="failed", error=str(exc))
        finally:
            self._persist_history(run_id)
