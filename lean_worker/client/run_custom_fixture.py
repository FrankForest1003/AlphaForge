#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from smoke_test import request


TERMINAL_STATES = {"completed", "completed_with_data_gaps", "failed", "timeout"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("algorithm", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    token = os.environ.get("ALPHAFORGE_API_TOKEN")
    if not token:
        raise SystemExit("ALPHAFORGE_API_TOKEN is required")
    code = args.algorithm.resolve().read_text(encoding="utf-8")
    submitted = request(
        "POST",
        f"{args.base_url}/v1/custom-jobs",
        token,
        {
            "algorithm_code": code,
            "parameters": {
                "symbols": "AAPL,MSFT,GOOGL,META,NVDA,AMZN",
                "start_date": "2024-01-29",
                "end_date": "2024-02-09",
                "initial_cash": "100000",
                "validation_mode": "gap_regression",
            },
            "timeout_seconds": args.timeout_seconds,
        },
    )
    run_id = submitted["run_id"]
    print(f"RUN_ID={run_id}")
    deadline = time.monotonic() + args.timeout_seconds + 120
    while True:
        status = request("GET", f"{args.base_url}/v1/jobs/{run_id}", token)
        print(f"state={status['state']}")
        if status["state"] in TERMINAL_STATES:
            break
        if time.monotonic() > deadline:
            raise SystemExit(f"Polling timed out for {run_id}")
        time.sleep(2)

    result = request(
        "GET",
        f"{args.base_url}/v1/jobs/{run_id}/result",
        token,
        timeout=120,
    )
    print(
        json.dumps(
            {
                "run_id": run_id,
                "status": result.get("status"),
                "summary": result.get("summary"),
                "error_lines": result.get("diagnostics", {}).get("error_lines"),
                "order_list_hash": result.get("statistics", {}).get("order_list_hash"),
            },
            indent=2,
        )
    )
    if result.get("status") != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
