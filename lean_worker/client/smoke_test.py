#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def request(method: str, url: str, token: str | None = None, body=None, timeout: int = 60):
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Worker-Token"] = token
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {payload}") from exc


def run_one(base: str, token: str, strategy_id: str, timeout_seconds: int):
    job = request(
        "POST",
        f"{base}/v1/jobs",
        token,
        {"strategy_id": strategy_id, "timeout_seconds": timeout_seconds},
    )
    run_id = job["run_id"]
    print(f"{strategy_id}: RUN_ID={run_id}")
    deadline = time.monotonic() + timeout_seconds + 120
    while True:
        status = request("GET", f"{base}/v1/jobs/{run_id}", token)
        print(f"{strategy_id}: state={status['state']}")
        if status["state"] == "completed":
            break
        if status["state"] in {"failed", "timeout", "completed_with_data_gaps"}:
            raise SystemExit(json.dumps(status, indent=2))
        if time.monotonic() > deadline:
            raise SystemExit(f"Client polling timed out for {run_id}")
        time.sleep(3)
    result = request("GET", f"{base}/v1/jobs/{run_id}/result", token, timeout=120)
    assert result["status"] == "completed"
    assert result["engine"]["clean_shutdown"] is True
    assert result["data_quality"].get("failed_requests", 0) == 0
    assert result["diagnostics"]["error_lines"] == []
    assert result.get("dataset", {}).get("manifest", {}).get("ready") is True
    assert len(result["performance"]["equity_curve"]) > 0
    assert len(result["performance"].get("benchmark_curve", [])) > 0
    assert len(result["portfolio"]["position_snapshots"]) > 0
    if strategy_id.startswith("ml_"):
        assert len(result["ml"]["training_runs"]) > 0
        assert len(result["ml"]["predictions"]) > 0
    print(
        json.dumps(
            {
                "strategy_id": strategy_id,
                "status": result["status"],
                "dataset_version": result.get("dataset", {})
                .get("manifest", {})
                .get("data_version"),
                "summary": result["summary"],
                "position_snapshots": len(result["portfolio"]["position_snapshots"]),
                "fills": len(result["execution"]["fills"]),
                "closed_trades": len(result["execution"]["closed_trades"]),
                "ml_training_runs": len(result["ml"]["training_runs"]),
                "ml_predictions": len(result["ml"]["predictions"]),
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--strategies",
        default="classic_30_stock_top3_momentum_v1,ml_30_stock_gradient_boosting_v1",
    )
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()
    health = request("GET", f"{args.base_url}/health")
    print(json.dumps(health, indent=2))
    data_status = request("GET", f"{args.base_url}/v1/data/status", args.token)
    print(json.dumps(data_status, indent=2))
    if not data_status.get("ready"):
        raise SystemExit(
            "Real data is not ready. Run scripts/data-sync.ps1 or scripts/data-sync.sh first."
        )
    print(json.dumps(request("GET", f"{args.base_url}/v1/strategies", args.token), indent=2))
    for strategy_id in [item.strip() for item in args.strategies.split(",") if item.strip()]:
        run_one(args.base_url, args.token, strategy_id, args.timeout_seconds)
    print("ALPHAFORGE_LOCAL_RUNTIME_PASS")


if __name__ == "__main__":
    main()
