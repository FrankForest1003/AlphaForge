from __future__ import annotations

from pathlib import Path
from typing import Any


STATISTICS = {
    "Compounding Annual Return": ("cagr", "percent"),
    "Drawdown": ("maximum_drawdown", "percent"),
    "Sharpe Ratio": ("sharpe_ratio", "float"),
    "End Equity": ("end_equity", "float"),
}


def parse_value(value: str, kind: str) -> Any:
    cleaned = value.replace(",", "").replace("$", "").strip()
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1].strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number / 100.0 if kind == "percent" else number


def parse_log_file(
    log_path: Path,
    *,
    exit_code: int | None,
    run_id: str,
    expected_marker: str | None,
    timed_out: bool,
) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    summary: dict[str, Any] = {}
    errors: list[str] = []
    failed_data_requests = 0
    order_error_count = 0
    first_order_error: str | None = None

    for line in text.splitlines():
        if "STATISTICS::" in line:
            payload = line.split("STATISTICS::", 1)[1].strip()
            for name in sorted(STATISTICS, key=len, reverse=True):
                if payload.startswith(name + " "):
                    key, kind = STATISTICS[name]
                    value = parse_value(payload[len(name) + 1 :], kind)
                    if value is not None:
                        summary[key] = value
                    break
        elif "DATA USAGE::" in line:
            payload = line.split("DATA USAGE::", 1)[1].strip()
            if not payload.startswith("Failed data requests ") or payload.startswith(
                "Failed data requests percentage "
            ):
                continue
            value = payload[len("Failed data requests ") :].strip()
            try:
                failed_data_requests = int(float(value))
            except ValueError:
                failed_data_requests = 1
        elif "Order Error:" in line:
            order_error_count += 1
            if first_order_error is None:
                first_order_error = line
        elif (
            " ERROR::" in line
            or line.startswith("ERROR::")
            or "Unhandled exception." in line
        ) and "Warning:" not in line:
            if line not in errors:
                errors.append(line)

    if order_error_count:
        errors.append(
            f"{order_error_count} order errors; first error: {first_order_error}"
        )

    analysis_completed = (
        "Engine.Main(): Analysis Completed and Results Posted." in text
        or "Engine.Main(): Analysis Complete." in text
    )
    marker_found = expected_marker in text if expected_marker else True

    if timed_out:
        status = "timeout"
        errors.append("LEAN execution timed out")
    elif exit_code not in (None, 0):
        status = "failed"
        errors.append(f"LEAN exited with code {exit_code}")
    elif not analysis_completed:
        status = "failed"
        errors.append("LEAN did not complete its analysis")
    elif not marker_found:
        status = "failed"
        errors.append("Strategy completion marker was not emitted")
    elif errors:
        status = "failed"
    elif failed_data_requests:
        status = "completed_with_data_gaps"
        errors.append(f"LEAN reported {failed_data_requests} failed data requests")
    else:
        status = "completed"

    return {
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "errors": errors,
    }
