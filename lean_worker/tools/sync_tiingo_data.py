#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests

API_ROOT = "https://api.tiingo.com/tiingo/daily"
CATALOG_DIRNAME = "alphaforge-catalog"
PRICE_SCALE = 10_000


class DataSyncError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise DataSyncError(
            f"A data synchronization is already running, or a stale lock exists: {path}"
        ) from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} started={utc_now()}\n".encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def load_universe(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = list(payload.get("tradable_symbols", [])) + list(
        payload.get("analysis_dependencies", [])
    )
    if len(payload.get("tradable_symbols", [])) != 30:
        raise DataSyncError("The configured default universe must contain exactly 30 tradable symbols")
    seen: set[str] = set()
    for entry in entries:
        required = {"lean_ticker", "tiingo_ticker", "exchange"}
        missing = required.difference(entry)
        if missing:
            raise DataSyncError(f"Universe entry is missing fields {sorted(missing)}: {entry}")
        ticker = str(entry["lean_ticker"]).upper()
        if ticker in seen:
            raise DataSyncError(f"Duplicate LEAN ticker in universe: {ticker}")
        seen.add(ticker)
    return payload, entries


def select_entries(entries: list[dict[str, Any]], symbols: str | None) -> list[dict[str, Any]]:
    if not symbols:
        return entries
    requested = {item.strip().upper() for item in symbols.split(",") if item.strip()}
    by_ticker = {str(item["lean_ticker"]).upper(): item for item in entries}
    unknown = sorted(requested.difference(by_ticker))
    if unknown:
        raise DataSyncError(f"Unknown symbols requested: {', '.join(unknown)}")
    return [by_ticker[ticker] for ticker in sorted(requested)]


def request_prices(
    session: requests.Session,
    *,
    token: str,
    source_ticker: str,
    start_date: date,
    end_date: date,
    retries: int,
) -> list[dict[str, Any]]:
    url = f"{API_ROOT}/{quote(source_ticker, safe='-._')}/prices"
    params = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "resampleFreq": "daily",
        "format": "json",
    }
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "AlphaForge-Local-LEAN-Runtime/1.1.3",
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, headers=headers, timeout=(15, 120))
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(120.0, 5.0 * (2 ** attempt))
                print(f"RATE_LIMITED ticker={source_ticker} sleep={delay:.1f}s", flush=True)
                time.sleep(delay)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise DataSyncError(f"Unexpected Tiingo response for {source_ticker}")
            return payload
        except (requests.RequestException, ValueError, DataSyncError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            delay = min(60.0, 2.0 * (2 ** attempt))
            print(
                f"RETRY ticker={source_ticker} attempt={attempt + 1}/{retries} sleep={delay:.1f}s error={exc}",
                flush=True,
            )
            time.sleep(delay)
    raise DataSyncError(f"Tiingo request failed for {source_ticker}: {last_error}")


def parse_date(value: Any) -> date:
    if not value:
        raise DataSyncError("Price row has no date")
    return date.fromisoformat(str(value)[:10])


def numeric(row: dict[str, Any], adjusted_key: str, raw_key: str) -> float:
    value = row.get(adjusted_key)
    if value is None:
        value = row.get(raw_key)
    if value is None:
        raise DataSyncError(f"Missing both {adjusted_key} and {raw_key}")
    return float(value)


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    trading_date = parse_date(row.get("date"))
    open_price = numeric(row, "adjOpen", "open")
    high_price = numeric(row, "adjHigh", "high")
    low_price = numeric(row, "adjLow", "low")
    close_price = numeric(row, "adjClose", "close")
    volume_value = row.get("adjVolume")
    if volume_value is None:
        volume_value = row.get("volume", 0)
    volume = max(0, int(round(float(volume_value))))
    if min(open_price, high_price, low_price, close_price) <= 0:
        raise DataSyncError(f"Non-positive OHLC on {trading_date}")
    high_price = max(high_price, open_price, low_price, close_price)
    low_price = min(low_price, open_price, high_price, close_price)
    return {
        "date": trading_date,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "div_cash": float(row.get("divCash") or 0.0),
        "split_factor": float(row.get("splitFactor") or 1.0),
    }


def lean_line(row: dict[str, Any]) -> str:
    def scaled(value: float) -> int:
        return int(round(float(value) * PRICE_SCALE))

    return ",".join(
        [
            row["date"].strftime("%Y%m%d 00:00"),
            str(scaled(row["open"])),
            str(scaled(row["high"])),
            str(scaled(row["low"])),
            str(scaled(row["close"])),
            str(int(row["volume"])),
        ]
    )


def parse_lean_line(line: str) -> tuple[date, str]:
    stripped = line.strip()
    if not stripped:
        raise ValueError("blank")
    day = datetime.strptime(stripped[:8], "%Y%m%d").date()
    return day, stripped


def read_existing_zip(path: Path, ticker_lower: str) -> dict[date, str]:
    if not path.is_file():
        return {}
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        target = f"{ticker_lower}.csv"
        name = target if target in names else (names[0] if names else None)
        if not name:
            return {}
        text = archive.read(name).decode("utf-8-sig", errors="strict")
    result: dict[date, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        day, normalized = parse_lean_line(line)
        result[day] = normalized
    return result


def write_daily_zip(path: Path, ticker_lower: str, rows: dict[date, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent, suffix=".zip") as handle:
        temp_path = Path(handle.name)
    try:
        content = "\n".join(rows[day] for day in sorted(rows)) + "\n"
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{ticker_lower}.csv", content)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_compatibility_files(data_root: Path, entry: dict[str, Any], first_date: date) -> None:
    ticker_lower = str(entry["lean_ticker"]).lower()
    exchange = str(entry["exchange"])
    factors = data_root / "equity/usa/factor_files"
    maps = data_root / "equity/usa/map_files"
    factors.mkdir(parents=True, exist_ok=True)
    maps.mkdir(parents=True, exist_ok=True)
    factor_text = f"{first_date.strftime('%Y%m%d')},1,1,0\n20501231,1,1,0\n"
    map_text = (
        f"{first_date.strftime('%Y%m%d')},{ticker_lower},{exchange}\n"
        f"20501231,{ticker_lower},{exchange}\n"
    )
    (factors / f"{ticker_lower}.csv").write_text(factor_text, encoding="utf-8")
    (maps / f"{ticker_lower}.csv").write_text(map_text, encoding="utf-8")


def inspect_zip(path: Path, ticker_lower: str) -> dict[str, Any]:
    rows = read_existing_zip(path, ticker_lower)
    invalid = 0
    previous: date | None = None
    for day, line in sorted(rows.items()):
        parts = line.split(",")
        try:
            values = [int(value) for value in parts[1:6]]
            open_value, high_value, low_value, close_value, volume = values
            if min(open_value, high_value, low_value, close_value) <= 0 or volume < 0:
                invalid += 1
            if high_value < max(open_value, low_value, close_value):
                invalid += 1
            if low_value > min(open_value, high_value, close_value):
                invalid += 1
            if previous is not None and day <= previous:
                invalid += 1
        except (ValueError, IndexError):
            invalid += 1
        previous = day
    ordered = sorted(rows)
    return {
        "rows": len(ordered),
        "first_date": ordered[0].isoformat() if ordered else None,
        "last_date": ordered[-1].isoformat() if ordered else None,
        "invalid_rows": invalid,
        "dates": ordered,
    }


def write_catalog(
    *,
    data_root: Path,
    universe: dict[str, Any],
    entries: list[dict[str, Any]],
    provider_start: date,
    requested_end: date,
    errors: list[dict[str, str]],
    corporate_actions: dict[str, list[dict[str, Any]]],
    sync_mode: str,
) -> dict[str, Any]:
    catalog = data_root / CATALOG_DIRNAME
    catalog.mkdir(parents=True, exist_ok=True)
    daily = data_root / "equity/usa/daily"
    reports: dict[str, dict[str, Any]] = {}
    for entry in entries:
        ticker = str(entry["lean_ticker"]).upper()
        ticker_lower = ticker.lower()
        info = inspect_zip(daily / f"{ticker_lower}.zip", ticker_lower)
        reports[ticker] = info

    available = [ticker for ticker, info in reports.items() if info["rows"] > 0]
    missing = sorted(set(reports).difference(available))
    dates_with_data = [date.fromisoformat(info["last_date"]) for info in reports.values() if info["last_date"]]
    first_dates = [date.fromisoformat(info["first_date"]) for info in reports.values() if info["first_date"]]
    common_end = min(dates_with_data) if len(dates_with_data) == len(entries) else None
    earliest = min(first_dates) if first_dates else None
    reference_dates = set(reports.get("SPY", {}).get("dates", []))
    quality_symbols = []
    for entry in entries:
        ticker = str(entry["lean_ticker"]).upper()
        info = reports[ticker]
        symbol_dates = set(info.pop("dates", []))
        missing_reference_dates = []
        if common_end and info["first_date"] and reference_dates:
            first = date.fromisoformat(info["first_date"])
            relevant = {day for day in reference_dates if first <= day <= common_end}
            missing_reference_dates = sorted(relevant.difference(symbol_dates))
            denominator = max(1, len(relevant))
            missing_ratio = len(missing_reference_dates) / denominator
        else:
            missing_ratio = 1.0 if not symbol_dates else 0.0
        quality_symbols.append(
            {
                "ticker": ticker,
                **info,
                "missing_vs_spy_count": len(missing_reference_dates),
                "missing_vs_spy_ratio": round(missing_ratio, 8),
                "sample_missing_dates": [d.isoformat() for d in missing_reference_dates[:20]],
            }
        )

    error_symbols = {item["ticker"] for item in errors}
    failed_quality = [
        item["ticker"]
        for item in quality_symbols
        if item["rows"] < 1000
        or item["invalid_rows"] > 0
        or item["missing_vs_spy_ratio"] > 0.02
    ]
    ready = not missing and not errors and not failed_quality and common_end is not None

    with (catalog / "symbols.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "display_ticker",
                "lean_ticker",
                "tiingo_ticker",
                "exchange",
                "sector",
                "role",
            ],
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    "display_ticker": entry.get("display_ticker", entry["lean_ticker"]),
                    "lean_ticker": entry["lean_ticker"],
                    "tiingo_ticker": entry["tiingo_ticker"],
                    "exchange": entry["exchange"],
                    "sector": entry.get("sector", ""),
                    "role": entry.get("role", "tradable"),
                }
            )

    with (catalog / "availability.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "rows",
                "first_date",
                "last_date",
                "invalid_rows",
                "missing_vs_spy_count",
                "missing_vs_spy_ratio",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(quality_symbols)

    quality_report = {
        "schema_version": "1.0",
        "generated_at_utc": utc_now(),
        "ready": ready,
        "required_symbol_count": len(entries),
        "available_symbol_count": len(available),
        "missing_symbols": missing,
        "provider_errors": errors,
        "failed_quality_symbols": sorted(set(failed_quality).union(error_symbols)),
        "common_end_date": common_end.isoformat() if common_end else None,
        "symbols": quality_symbols,
    }
    write_json(catalog / "quality_report.json", quality_report)
    write_json(catalog / "corporate_actions.json", corporate_actions)

    manifest = {
        "schema_version": "1.0",
        "data_version": (
            f"tiingo-eod-adjusted-v1-{common_end.strftime('%Y%m%d')}"
            if common_end
            else f"tiingo-eod-adjusted-v1-incomplete-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        ),
        "source": "Tiingo End-of-Day Prices API",
        "provider": "tiingo",
        "attribution": "Data sourced by Tiingo",
        "license_scope": "internal-use-only; each user supplies their own Tiingo API token",
        "universe_id": universe.get("universe_id"),
        "universe_version": "whitelist_v1.0",
        "asset_class": "US Equity",
        "resolution": "Daily",
        "requested_start_date": provider_start.isoformat(),
        "requested_end_date": requested_end.isoformat(),
        "raw_start_date": earliest.isoformat() if earliest else None,
        "experiment_start_date": "2015-01-02",
        "common_end_date": common_end.isoformat() if common_end else None,
        "downloaded_at_utc": utc_now(),
        "sync_mode": sync_mode,
        "normalization_policy": (
            "Tiingo adjusted OHLCV is stored in LEAN daily format and consumed with "
            "DataNormalizationMode.RAW to avoid double adjustment."
        ),
        "security_master_policy": (
            "Neutral compatibility map/factor files for a frozen current-ticker universe. "
            "This is not the official QuantConnect Security Master."
        ),
        "tradable_symbols": [str(item["lean_ticker"]).upper() for item in universe["tradable_symbols"]],
        "analysis_dependencies": [
            str(item["lean_ticker"]).upper() for item in universe["analysis_dependencies"]
        ],
        "contains_factor_files": True,
        "contains_map_files": True,
        "ready": ready,
    }
    write_json(catalog / "dataset_manifest.json", manifest)

    checksum_paths: list[Path] = []
    for subdir in ["equity/usa/daily", "equity/usa/factor_files", "equity/usa/map_files"]:
        root = data_root / subdir
        if root.is_dir():
            checksum_paths.extend(path for path in root.iterdir() if path.is_file())
    checksum_paths.extend(
        path
        for path in catalog.iterdir()
        if path.is_file() and path.name != "checksums.json"
    )
    checksums = {
        str(path.relative_to(data_root)).replace("\\", "/"): sha256_file(path)
        for path in sorted(checksum_paths)
    }
    write_json(catalog / "checksums.json", checksums)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download licensed Tiingo EOD data and convert it to portable LEAN daily ZIP files."
    )
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--symbols", help="Optional comma-separated LEAN tickers")
    parser.add_argument("--full", action="store_true", help="Replace each selected symbol from --start")
    parser.add_argument("--overlap-days", type=int, default=14)
    parser.add_argument("--request-delay", type=float, default=1.1)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--token-env", default="TIINGO_API_TOKEN")
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token or token.lower().startswith("replace-"):
        raise DataSyncError(
            f"Environment variable {args.token_env} is empty. Configure your own Tiingo API token first."
        )
    start_date = date.fromisoformat(args.start)
    requested_end = date.fromisoformat(args.end)
    if requested_end < start_date:
        raise DataSyncError("--end must not be earlier than --start")

    universe, all_entries = load_universe(args.universe)
    selected_entries = select_entries(all_entries, args.symbols)
    data_root = args.data_root.resolve()
    daily_root = data_root / "equity/usa/daily"
    daily_root.mkdir(parents=True, exist_ok=True)
    catalog = data_root / CATALOG_DIRNAME
    existing_manifest_path = catalog / "dataset_manifest.json"
    existing_manifest = (
        json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        if existing_manifest_path.is_file()
        else {}
    )
    provider_matches = existing_manifest.get("provider") == "tiingo"

    errors: list[dict[str, str]] = []
    existing_actions_path = catalog / "corporate_actions.json"
    corporate_actions: dict[str, list[dict[str, Any]]] = (
        json.loads(existing_actions_path.read_text(encoding="utf-8"))
        if existing_actions_path.is_file()
        else {}
    )
    session = requests.Session()
    lock_path = data_root / ".alphaforge-data-sync.lock"
    with exclusive_lock(lock_path):
        for index, entry in enumerate(selected_entries, 1):
            ticker = str(entry["lean_ticker"]).upper()
            ticker_lower = ticker.lower()
            source_ticker = str(entry["tiingo_ticker"])
            zip_path = daily_root / f"{ticker_lower}.zip"
            existing_rows = read_existing_zip(zip_path, ticker_lower)
            full_refresh = args.full or not provider_matches or not existing_rows
            if full_refresh:
                request_start = start_date
                merged_rows: dict[date, str] = {}
            else:
                latest = max(existing_rows)
                request_start = max(start_date, latest - timedelta(days=max(0, args.overlap_days)))
                merged_rows = dict(existing_rows)
            print(
                f"SYNC {index}/{len(selected_entries)} ticker={ticker} source={source_ticker} "
                f"start={request_start} end={requested_end} mode={'full' if full_refresh else 'incremental'}",
                flush=True,
            )
            try:
                payload = request_prices(
                    session,
                    token=token,
                    source_ticker=source_ticker,
                    start_date=request_start,
                    end_date=requested_end,
                    retries=args.retries,
                )
                normalized = [normalize_row(row) for row in payload]
                if not normalized:
                    raise DataSyncError(f"No price rows returned for {source_ticker}")
                actions = []
                for row in normalized:
                    merged_rows[row["date"]] = lean_line(row)
                    if row["div_cash"] != 0.0 or row["split_factor"] != 1.0:
                        actions.append(
                            {
                                "date": row["date"].isoformat(),
                                "div_cash": row["div_cash"],
                                "split_factor": row["split_factor"],
                            }
                        )
                write_daily_zip(zip_path, ticker_lower, merged_rows)
                write_compatibility_files(data_root, entry, min(merged_rows))
                if full_refresh:
                    corporate_actions[ticker] = actions
                else:
                    prior_actions = {
                        str(item.get("date")): item
                        for item in corporate_actions.get(ticker, [])
                        if item.get("date")
                    }
                    for item in actions:
                        prior_actions[item["date"]] = item
                    corporate_actions[ticker] = [
                        prior_actions[key] for key in sorted(prior_actions)
                    ]
                print(
                    f"SYNCED ticker={ticker} rows={len(merged_rows)} first={min(merged_rows)} last={max(merged_rows)}",
                    flush=True,
                )
            except Exception as exc:
                errors.append({"ticker": ticker, "error": str(exc)})
                print(f"SYNC_ERROR ticker={ticker} error={exc}", file=sys.stderr, flush=True)
            if index < len(selected_entries) and args.request_delay > 0:
                time.sleep(args.request_delay)

        manifest = write_catalog(
            data_root=data_root,
            universe=universe,
            entries=all_entries,
            provider_start=start_date,
            requested_end=requested_end,
            errors=errors,
            corporate_actions=corporate_actions,
            sync_mode="full" if args.full else "incremental",
        )

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if errors or not manifest.get("ready"):
        print("ALPHAFORGE_REAL_DATA_SYNC_INCOMPLETE", file=sys.stderr)
        return 2
    print("ALPHAFORGE_REAL_DATA_READY")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DataSyncError as exc:
        print(f"DATA_SYNC_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
