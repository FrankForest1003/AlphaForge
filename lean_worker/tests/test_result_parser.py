from pathlib import Path

from worker.result_parser import parse_log_file


def test_parser_returns_only_status_summary_and_errors(tmp_path: Path):
    log = tmp_path / "console.log"
    log.write_text(
        "STATISTICS:: Compounding Annual Return 12.5%\n"
        "STATISTICS:: Drawdown 8.0%\n"
        "STATISTICS:: Sharpe Ratio 1.2\n"
        "STATISTICS:: Sortino Ratio 1.8\n"
        "STATISTICS:: Annual Standard Deviation 0.22\n"
        "STATISTICS:: Portfolio Turnover 45.5%\n"
        "STATISTICS:: Total Fees $125.50\n"
        "STATISTICS:: End Equity 112500\n"
        "STATISTICS:: Drawdown Recovery 12\n"
        "DATA USAGE:: Failed data requests 0\n"
        "DATA USAGE:: Failed data requests percentage 0%\n"
        "Engine.Main(): Analysis Complete.\n"
        "MARKER\n",
        encoding="utf-8",
    )
    result = parse_log_file(
        log,
        exit_code=0,
        run_id="r",
        expected_marker="MARKER",
        timed_out=False,
    )

    assert set(result) == {"run_id", "status", "summary", "errors"}
    assert result["status"] == "completed"
    assert result["summary"] == {
        "cagr": 0.125,
        "maximum_drawdown": 0.08,
        "sharpe_ratio": 1.2,
        "sortino_ratio": 1.8,
        "annualized_volatility": 0.22,
        "portfolio_turnover": 0.455,
        "total_fees": 125.5,
        "end_equity": 112500.0,
    }
    assert result["errors"] == []


def test_explicit_warning_is_not_a_failure(tmp_path: Path):
    log = tmp_path / "console.log"
    log.write_text(
        "ERROR:: Warning: order LimitPrice was rounded\n"
        "Engine.Main(): Analysis Complete.\n"
        "MARKER\n",
        encoding="utf-8",
    )
    result = parse_log_file(
        log,
        exit_code=0,
        run_id="r",
        expected_marker="MARKER",
        timed_out=False,
    )

    assert result["status"] == "completed"
    assert result["errors"] == []


def test_repeated_order_errors_are_aggregated(tmp_path: Path):
    log = tmp_path / "console.log"
    log.write_text(
        "ERROR:: Order Error: first\n"
        "ERROR:: Order Error: second\n"
        "Engine.Main(): Analysis Complete.\n",
        encoding="utf-8",
    )
    result = parse_log_file(
        log,
        exit_code=0,
        run_id="r",
        expected_marker=None,
        timed_out=False,
    )

    assert result["status"] == "failed"
    assert result["errors"] == [
        "2 order errors; first error: ERROR:: Order Error: first"
    ]
