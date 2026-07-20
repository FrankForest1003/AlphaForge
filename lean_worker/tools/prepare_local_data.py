#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import zipfile
from datetime import date, timedelta
from pathlib import Path

SYMBOLS = {
    "aapl": {"start": 75.0, "drift": 0.00050, "vol": 0.018, "exchange": "Q", "seed": 101},
    "msft": {"start": 110.0, "drift": 0.00055, "vol": 0.016, "exchange": "Q", "seed": 202},
    "spy": {"start": 250.0, "drift": 0.00035, "vol": 0.010, "exchange": "P", "seed": 303},
}


def copy_metadata(template: Path, data: Path) -> None:
    for relative in ["market-hours", "symbol-properties", "alternative/interest-rate"]:
        src = template / relative
        dst = data / relative
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)


def business_days(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def scaled(value: float) -> int:
    return int(round(value * 10000))


def generate_symbol(ticker: str, cfg: dict, data: Path) -> dict:
    rng = random.Random(cfg["seed"])
    price = float(cfg["start"])
    lines = []
    for current in business_days(date(2019, 1, 2), date(2025, 12, 31)):
        cycle = 0.00025 * math.sin((current.toordinal() + cfg["seed"]) / 37.0)
        shock = rng.gauss(cfg["drift"] + cycle, cfg["vol"])
        open_price = max(1.0, price * (1 + rng.gauss(0, cfg["vol"] * 0.2)))
        close = max(1.0, open_price * (1 + shock))
        high = max(open_price, close) * (1 + abs(rng.gauss(0, 0.004)))
        low = min(open_price, close) * (1 - abs(rng.gauss(0, 0.004)))
        volume = int(20_000_000 + abs(rng.gauss(0, 8_000_000)))
        lines.append(",".join([
            current.strftime("%Y%m%d 00:00"),
            str(scaled(open_price)), str(scaled(high)), str(scaled(low)), str(scaled(close)), str(volume),
        ]))
        price = close

    daily = data / "equity/usa/daily"
    daily.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(daily / f"{ticker}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{ticker}.csv", "\n".join(lines) + "\n")

    factor = data / "equity/usa/factor_files"
    maps = data / "equity/usa/map_files"
    factor.mkdir(parents=True, exist_ok=True)
    maps.mkdir(parents=True, exist_ok=True)
    (factor / f"{ticker}.csv").write_text("19980102,1,1,0\n20501231,1,1,0\n", encoding="utf-8")
    (maps / f"{ticker}.csv").write_text(
        f"19980102,{ticker},{cfg['exchange']}\n20501231,{ticker},{cfg['exchange']}\n",
        encoding="utf-8",
    )
    return {"ticker": ticker.upper(), "rows": len(lines), "last_price": price}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-data", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--generate-sample", action="store_true")
    args = parser.parse_args()
    args.data_root.mkdir(parents=True, exist_ok=True)
    copy_metadata(args.template_data, args.data_root)
    daily = args.data_root / "equity/usa/daily"
    missing = [ticker for ticker in SYMBOLS if not (daily / f"{ticker}.zip").is_file()]
    reports = []
    if args.generate_sample and missing:
        for ticker in missing:
            reports.append(generate_symbol(ticker, SYMBOLS[ticker], args.data_root))
    if args.generate_sample:
        catalog = args.data_root / "alphaforge-catalog"
        catalog.mkdir(parents=True, exist_ok=True)
        manifest = {
            "type": "deterministic_synthetic_smoke_test_data",
            "warning": "For deployment validation only. Replace with licensed/approved real market data for evaluation.",
            "symbols": list(SYMBOLS),
            "generated": reports,
        }
        (catalog / "sample_data_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
    print("LOCAL_DATA_READY")


if __name__ == "__main__":
    main()
