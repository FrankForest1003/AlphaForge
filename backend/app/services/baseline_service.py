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

from agent import ACCEPTANCE_CHECK_IDS, DESIGNER_TRACKS
from app.schemas import GuidedHumanStrategy, HumanStrategyRequest, RunSettings
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
AGENT_ACCEPTANCE_LOG_MAX_CHARS = 120_000
AGENT_REPAIR_LOG_MAX_CHARS = 400_000
AGENT_RESULT_ERRORS_MAX_CHARS = 100_000
AGENT_FAILURE_EXCERPT_MAX_CHARS = 100_000


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
    "STATISTICS::",
    "DATA USAGE::",
)


def extract_critical_log_evidence(console_log: str) -> str:
    return "\n".join(
        line
        for line in console_log.splitlines()
        if any(marker in line for marker in CRITICAL_LOG_MARKERS)
    )


def _bounded_text(text: str, *, max_chars: int, label: str) -> str:
    if len(text) <= max_chars:
        return text
    header = f"[{label}: original_chars={len(text)}, bounded_chars={max_chars}]\n"
    separator = "\n[... middle text omitted from Agent context ...]\n"
    budget = max_chars - len(header) - len(separator)
    head_chars = max(0, int(budget * 0.55))
    tail_chars = max(0, budget - head_chars)
    return header + text[:head_chars] + separator + text[-tail_chars:]


def compact_console_log(console_log: str, *, max_chars: int) -> str:
    """Build a bounded Agent view while the Worker trace retains the full log."""

    if len(console_log) <= max_chars:
        return console_log
    lines = console_log.splitlines()
    selected: set[int] = set(range(min(30, len(lines))))
    selected.update(range(max(0, len(lines) - 100), len(lines)))
    for index, line in enumerate(lines):
        if any(marker in line for marker in AGENT_LOG_MARKERS):
            selected.update(range(max(0, index - 2), min(len(lines), index + 3)))
    excerpt = "\n".join(lines[index] for index in sorted(selected))
    return _bounded_text(
        excerpt,
        max_chars=max_chars,
        label=(
            "AlphaForge Agent log view "
            f"original_chars={len(console_log)} selected_lines={len(selected)}"
        ),
    )


def compact_worker_result(result: dict[str, Any]) -> dict[str, Any]:
    view = copy.deepcopy(result)
    errors = view.get("errors")
    if not isinstance(errors, list):
        return view
    error_text = "\n".join(str(item) for item in errors)
    if len(error_text) <= AGENT_RESULT_ERRORS_MAX_CHARS:
        return view
    view["errors"] = [
        _bounded_text(
            error_text,
            max_chars=AGENT_RESULT_ERRORS_MAX_CHARS,
            label="AlphaForge Worker error view",
        )
    ]
    view["errors_context"] = {
        "original_error_count": len(errors),
        "original_error_chars": len(error_text),
    }
    return view


def compact_runtime_failure_evidence(
    evidence: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if evidence is None:
        return None
    view = copy.deepcopy(evidence)
    excerpt = view.get("error_log_excerpt")
    if isinstance(excerpt, list):
        text = "\n".join(str(line) for line in excerpt)
        if len(text) > AGENT_FAILURE_EXCERPT_MAX_CHARS:
            view["error_log_excerpt"] = [
                _bounded_text(
                    text,
                    max_chars=AGENT_FAILURE_EXCERPT_MAX_CHARS,
                    label="AlphaForge failure log view",
                )
            ]
            view["error_log_context"] = {
                "original_line_count": len(excerpt),
                "original_chars": len(text),
            }
    return view


def extract_error_log_excerpt(console_log: str, order_id: int | None = None) -> list[str]:
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
    if not isinstance(details, dict):
        return {
            "details_available": False,
            "details_error": details_error or "alphaforge_details.json is unavailable",
            "failed_orders": [],
            "error_log_excerpt": extract_error_log_excerpt(console_log),
        }

    orders = details.get("orders")
    if not isinstance(orders, list):
        orders = []
    events = details.get("order_events")
    if not isinstance(events, list):
        events = []
    snapshots = details.get("position_snapshots")
    if not isinstance(snapshots, list):
        snapshots = []

    orders_by_id = {
        int(order["order_id"]): order
        for order in orders
        if isinstance(order, dict) and order.get("order_id") is not None
    }

    def time_key(value: Any) -> str:
        return str(value or "")[:19]

    failed_orders: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("order_id") is None:
            continue
        status = str(event.get("status", "")).strip().upper().split(".")[-1]
        message = str(event.get("message") or "")
        lowered_message = message.lower()
        if status not in {"INVALID", "REJECTED"} and not any(
            marker in lowered_message
            for marker in ("error", "insufficient", "failed", "rejected")
        ):
            continue

        order_id = int(event["order_id"])
        raw_order = orders_by_id.get(order_id, {})
        event_time = time_key(event.get("time"))
        prior_snapshots = [
            snapshot
            for snapshot in snapshots
            if isinstance(snapshot, dict)
            and time_key(snapshot.get("time")) <= event_time
        ]
        portfolio_before_failure = max(
            prior_snapshots,
            key=lambda snapshot: time_key(snapshot.get("time")),
            default=None,
        )
        failed_orders.append(
            {
                "order": {
                    "order_id": order_id,
                    "symbol": raw_order.get("symbol") or event.get("symbol"),
                    "quantity": raw_order.get("quantity"),
                    "type": raw_order.get("type"),
                    "status": raw_order.get("status") or event.get("status"),
                    "submitted_at": raw_order.get("time"),
                    "tag": raw_order.get("tag"),
                    "price": raw_order.get("price"),
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
        "error_log_excerpt": extract_error_log_excerpt(console_log),
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
        str(event.get("name", "")).strip()
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
    return {
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
            "staged_rebalance_removal_phase"
        ),
        "staged_rebalance_completed_count": rebalance_names.count(
            "staged_rebalance_completed"
        ),
        "staged_rebalance_replacement_count": rebalance_names.count(
            "staged_rebalance_replacement_requested"
        ),
        "latest_rebalance_event": (
            copy.deepcopy(rebalances[-1]) if rebalances else None
        ),
        "signal_event_count": len(signals),
        "latest_signal_event": copy.deepcopy(signals[-1]) if signals else None,
        "ml_training_run_count": len(training_runs),
        "latest_ml_training_run": (
            copy.deepcopy(training_runs[-1]) if training_runs else None
        ),
        "ml_prediction_count": len(predictions),
        "latest_ml_predictions": copy.deepcopy(predictions[-10:]),
    }


def validate_acceptance_report(
    report: dict[str, Any],
    behavior_evidence: dict[str, Any],
) -> dict[str, Any]:
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
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge")

    def _trace_path(self, run_id: str) -> Path:
        if self.trace_root is None:
            raise RuntimeError("Agent trace persistence is not configured")
        if not run_id.startswith("forge-") or not run_id[6:].isalnum():
            raise ValueError("invalid Forge run_id")
        return self.trace_root / f"{run_id}.json"

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
            "schema_version": "1.0",
            "run_id": run_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "state": "queued",
            "error": None,
            "run_settings": settings.model_dump(mode="json"),
            "baseline_results": [],
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
                    "summary": {},
                    "error": None,
                    "usage": {},
                    "repair_attempts": 0,
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
            return copy.deepcopy(run) if run is not None else None

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
        usage = self._add_usage({}, generated.get("usage", {}))
        self._change_item(
            run_id,
            "candidates",
            index,
            state="submitting",
            source_code=source_code,
            usage=usage,
            repair_attempts=0,
            error=None,
        )

        acceptance_history: list[dict[str, Any]] = []
        for repair_attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            runtime_failure_evidence = None
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
                        worker_result=compact_worker_result(result),
                        lean_console_log=compact_console_log(
                            console_log,
                            max_chars=AGENT_ACCEPTANCE_LOG_MAX_CHARS,
                        ),
                        behavior_evidence=behavior_evidence,
                        acceptance_attempt=acceptance_attempt,
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
                    report = validate_acceptance_report(
                        evaluated.get("report", {}), behavior_evidence
                    )
                except Exception as exc:
                    self._update_worker_attempt(
                        run_id=run_id,
                        worker_run_id=worker_run_id,
                        outcome="acceptance_response_invalid",
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                    raise
                acceptance_history.append(
                    {
                        "attempt": len(acceptance_history) + 1,
                        "worker_run_id": worker_run_id,
                        "behavior_evidence": behavior_evidence,
                        "report": report,
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
                    worker_result=compact_worker_result(result),
                    lean_console_log=compact_console_log(
                        console_log,
                        max_chars=AGENT_REPAIR_LOG_MAX_CHARS,
                    ),
                    repair_attempt=next_attempt,
                    repair_trigger=repair_trigger,
                    runtime_failure_evidence=compact_runtime_failure_evidence(
                        runtime_failure_evidence
                    ),
                    acceptance_report=acceptance_report,
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
            self._change_item(
                run_id,
                "candidates",
                index,
                state="submitting",
                source_code=source_code,
                usage=usage,
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
