from __future__ import annotations

import copy
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
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


def extract_critical_log_evidence(console_log: str) -> str:
    return "\n".join(
        line
        for line in console_log.splitlines()
        if any(marker in line for marker in CRITICAL_LOG_MARKERS)
    )


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
    return {
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
    """One in-memory flow for baselines and accepted Designer candidates."""

    def __init__(
        self,
        *,
        worker: LeanWorkerClient,
        designer: Any,
        repairer: Any,
        acceptance_agent: Any,
        allowed_symbols: set[str],
        allowed_benchmarks: set[str],
    ) -> None:
        self.worker = worker
        self.designer = designer
        self.repairer = repairer
        self.acceptance_agent = acceptance_agent
        self.allowed_symbols = {item.upper() for item in allowed_symbols}
        self.allowed_benchmarks = {item.upper() for item in allowed_benchmarks}
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge")

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
            submitted = self.worker.submit_custom(source_code, parameters)
            worker_run_id = submitted["run_id"]
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
                console_log = self.worker.log(worker_run_id)
                behavior_evidence = build_behavior_evidence(
                    self.worker.details(worker_run_id)
                )
                evaluated = self.acceptance_agent.evaluate(
                    track=track,
                    run_settings=settings.model_dump(mode="json"),
                    critical_log_evidence=extract_critical_log_evidence(console_log),
                    source_code=source_code,
                    worker_result=result,
                    lean_console_log=console_log,
                    behavior_evidence=behavior_evidence,
                    acceptance_attempt=len(acceptance_history) + 1,
                )
                usage = self._add_usage(usage, evaluated.get("usage", {}))
                self._change_item(run_id, "candidates", index, usage=usage)
                report = validate_acceptance_report(
                    evaluated.get("report", {}), behavior_evidence
                )
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
                    self._change_item(
                        run_id,
                        "candidates",
                        index,
                        state="accepted",
                        error=None,
                    )
                    return
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
                repair_reason = (
                    "; ".join(result.get("errors", [])) or "LEAN run failed"
                )
                try:
                    console_log = self.worker.log(worker_run_id)
                except Exception:
                    console_log = "\n".join(result.get("errors", []))

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
            )
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
        except Exception as exc:
            self._change(run_id, state="failed", stage="Stopped", error=str(exc))
