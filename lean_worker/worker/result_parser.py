from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "2.0"

STATISTIC_KEYS = {
    "Total Orders": ("total_orders", "int"),
    "Average Win": ("average_win", "percent"),
    "Average Loss": ("average_loss", "percent"),
    "Compounding Annual Return": ("compounding_annual_return", "percent"),
    "Drawdown": ("maximum_drawdown", "percent"),
    "Expectancy": ("expectancy", "float"),
    "Start Equity": ("start_equity", "float"),
    "End Equity": ("end_equity", "float"),
    "Net Profit": ("net_profit", "percent"),
    "Sharpe Ratio": ("sharpe_ratio", "float"),
    "Sortino Ratio": ("sortino_ratio", "float"),
    "Probabilistic Sharpe Ratio": ("probabilistic_sharpe_ratio", "percent"),
    "Loss Rate": ("loss_rate", "percent"),
    "Win Rate": ("win_rate", "percent"),
    "Profit-Loss Ratio": ("profit_loss_ratio", "float"),
    "Alpha": ("alpha", "float"),
    "Beta": ("beta", "float"),
    "Annual Standard Deviation": ("annual_standard_deviation", "float"),
    "Annual Variance": ("annual_variance", "float"),
    "Information Ratio": ("information_ratio", "float"),
    "Tracking Error": ("tracking_error", "float"),
    "Treynor Ratio": ("treynor_ratio", "float"),
    "Total Fees": ("total_fees", "currency"),
    "Estimated Strategy Capacity": ("estimated_strategy_capacity", "currency"),
    "Lowest Capacity Asset": ("lowest_capacity_asset", "str"),
    "Portfolio Turnover": ("portfolio_turnover", "percent"),
    "Drawdown Recovery": ("drawdown_recovery", "float"),
    "OrderListHash": ("order_list_hash", "str"),
}
DATA_KEYS = {
    "Total data requests": "total_requests",
    "Succeeded data requests": "succeeded_requests",
    "Failed data requests": "failed_requests",
    "Failed data requests percentage": "failed_requests_percentage",
    "Total universe data requests": "total_universe_requests",
    "Succeeded universe data requests": "succeeded_universe_requests",
    "Failed universe data requests": "failed_universe_requests",
    "Failed universe data requests percentage": "failed_universe_requests_percentage",
}


def parse_value(value: str, kind: str) -> Any:
    if kind == "str":
        return value.strip()
    cleaned = value.replace(",", "").replace("$", "").strip().removesuffix("%").strip()
    try:
        number = float(cleaned)
    except ValueError:
        return value.strip()
    if kind == "int":
        return int(number)
    if kind == "percent":
        return round(number / 100.0, 12)
    return number


def match_named(line: str, prefix: str, names: list[str]) -> tuple[str, str] | None:
    marker = prefix + " "
    pos = line.find(marker)
    if pos < 0:
        return None
    payload = line[pos + len(marker):].strip()
    for name in names:
        if payload.startswith(name + " "):
            return name, payload[len(name) + 1:].strip()
    return None


def compute_drawdown(equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak = None
    output = []
    for point in equity_curve:
        equity = float(point.get("portfolio_value", 0.0))
        peak = equity if peak is None else max(peak, equity)
        drawdown = 0.0 if not peak else equity / peak - 1.0
        output.append({"time": point.get("time"), "drawdown": drawdown})
    return output


def reconstruct_closed_trades(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lots: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    trades: list[dict[str, Any]] = []
    for fill in fills:
        symbol = str(fill.get("symbol"))
        qty = float(fill.get("fill_quantity") or 0)
        price = float(fill.get("fill_price") or 0)
        if qty == 0:
            continue
        remaining = qty
        queue = lots[symbol]
        while remaining and queue and queue[0]["quantity"] * remaining < 0:
            lot = queue[0]
            matched = min(abs(remaining), abs(lot["quantity"]))
            if lot["quantity"] > 0:
                pnl = (price - lot["price"]) * matched
                direction = "long"
            else:
                pnl = (lot["price"] - price) * matched
                direction = "short"
            trades.append({
                "symbol": symbol,
                "direction": direction,
                "entry_time": lot["time"],
                "exit_time": fill.get("time"),
                "entry_price": lot["price"],
                "exit_price": price,
                "quantity": matched,
                "profit_loss": pnl,
                "return": 0.0 if not lot["price"] else pnl / (lot["price"] * matched),
                "entry_order_id": lot.get("order_id"),
                "exit_order_id": fill.get("order_id"),
            })
            sign = 1 if lot["quantity"] > 0 else -1
            lot["quantity"] -= sign * matched
            remaining += sign * matched
            if abs(lot["quantity"]) < 1e-12:
                queue.popleft()
        if abs(remaining) > 1e-12:
            queue.append({
                "quantity": remaining,
                "price": price,
                "time": fill.get("time"),
                "order_id": fill.get("order_id"),
            })
    return trades


def parse_log_file(
    log_path: Path,
    *,
    detail_path: Path,
    exit_code: int | None,
    run_id: str,
    algorithm_class: str,
    algorithm_file: str,
    expected_marker: str | None,
    timed_out: bool,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    metrics: dict[str, Any] = {}
    raw_statistics: dict[str, str] = {}
    data_quality: dict[str, Any] = {}
    error_lines: list[str] = []
    warning_lines: list[str] = []
    statistic_names = sorted(STATISTIC_KEYS, key=len, reverse=True)
    data_names = sorted(DATA_KEYS, key=len, reverse=True)

    for line in text.splitlines():
        named = match_named(line, "STATISTICS::", statistic_names)
        if named:
            name, value = named
            raw_statistics[name] = value
            key, kind = STATISTIC_KEYS[name]
            metrics[key] = parse_value(value, kind)
            continue
        named = match_named(line, "DATA USAGE::", data_names)
        if named:
            name, value = named
            key = DATA_KEYS[name]
            data_quality[key] = parse_value(value, "percent" if "percentage" in key else "int")
            continue
        if " ERROR::" in line or line.startswith("ERROR::") or "Unhandled exception." in line or "Order Error:" in line:
            error_lines.append(line)
        elif " WARN" in line or "Warning:" in line:
            warning_lines.append(line)

    details: dict[str, Any] = {}
    if detail_path.is_file():
        details = json.loads(detail_path.read_text(encoding="utf-8"))

    analysis_completed = "Engine.Main(): Analysis Completed and Results Posted." in text or "Engine.Main(): Analysis Complete." in text
    python_shutdown_ended = "PythonInitializer.Shutdown(): ended" in text
    program_exited = "Program.Main(): Exiting Lean..." in text
    marker_found = expected_marker in text if expected_marker else True
    failed_requests = int(data_quality.get("failed_requests", 0))
    unhandled = "Unhandled exception." in text

    if timed_out:
        status = "timeout"
    elif unhandled or (exit_code not in (None, 0)) or not analysis_completed or not marker_found or error_lines:
        status = "failed"
    elif failed_requests > 0:
        status = "completed_with_data_gaps"
    else:
        status = "completed"

    equity_curve = details.get("equity_curve", [])
    order_events = details.get("order_events", [])
    fills = [e for e in order_events if float(e.get("fill_quantity") or 0) != 0]
    position_snapshots = details.get("position_snapshots", [])
    final_positions = position_snapshots[-1]["positions"] if position_snapshots else []

    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "status": status,
            "created_at_utc": manifest.get("created_at_utc"),
        },
        "status": status,
        "strategy": {
            "class_name": algorithm_class,
            "file": algorithm_file,
            "expected_marker": expected_marker,
            "marker_found": marker_found,
            "parameters": manifest.get("strategy", {}).get("parameters", {}),
            "sha256": manifest.get("strategy", {}).get("sha256"),
        },
        "environment": {
            "runtime_version": manifest.get("runtime_version"),
            "lean_commit": manifest.get("lean_commit"),
            **manifest.get("environment", {}),
        },
        "dataset": manifest.get("dataset", {}),
        "engine": {
            "exit_code": exit_code,
            "analysis_completed": analysis_completed,
            "python_shutdown_ended": python_shutdown_ended,
            "program_exited": program_exited,
            "clean_shutdown": status in {"completed", "completed_with_data_gaps"} and exit_code == 0 and analysis_completed and python_shutdown_ended and program_exited,
            "timed_out": timed_out,
        },
        "summary": {
            "cagr": metrics.get("compounding_annual_return"),
            "maximum_drawdown": metrics.get("maximum_drawdown"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "sortino_ratio": metrics.get("sortino_ratio"),
            "end_equity": metrics.get("end_equity"),
            "net_profit": metrics.get("net_profit"),
            "total_orders": metrics.get("total_orders"),
            "total_fees": metrics.get("total_fees"),
            "portfolio_turnover": metrics.get("portfolio_turnover"),
        },
        "statistics": metrics,
        "performance": {
            "equity_curve": equity_curve,
            "drawdown_curve": compute_drawdown(equity_curve),
            "benchmark_curve": details.get("benchmark_curve", []),
            "cash_curve": [
                {"time": point.get("time"), "cash": point.get("cash")}
                for point in equity_curve
            ],
            "exposure_curve": [
                {
                    "time": snapshot.get("time"),
                    "gross_exposure": snapshot.get("gross_exposure"),
                    "net_exposure": snapshot.get("net_exposure"),
                }
                for snapshot in position_snapshots
            ],
        },
        "portfolio": {
            "position_snapshots": position_snapshots,
            "final_positions": final_positions,
        },
        "execution": {
            "orders": details.get("orders", []),
            "order_events": order_events,
            "fills": fills,
            "closed_trades": reconstruct_closed_trades(fills),
        },
        "signals": details.get("signals", []),
        "ml": details.get("ml", {"training_runs": [], "predictions": [], "model_artifacts": []}),
        "data_quality": data_quality,
        "evaluation": {
            "eligible_for_comparison": status == "completed" and failed_requests == 0 and not error_lines,
            "rejection_reasons": [
                reason for condition, reason in [
                    (timed_out, "timeout"),
                    (unhandled, "unhandled_exception"),
                    (exit_code not in (None, 0), "nonzero_exit_code"),
                    (not analysis_completed, "analysis_not_completed"),
                    (not marker_found, "expected_marker_missing"),
                    (bool(error_lines), "lean_error_lines"),
                    (failed_requests > 0, "failed_data_requests"),
                ] if condition
            ],
        },
        "diagnostics": {
            "error_lines": error_lines,
            "warning_lines": warning_lines,
            "raw_statistics": raw_statistics,
        },
    }
