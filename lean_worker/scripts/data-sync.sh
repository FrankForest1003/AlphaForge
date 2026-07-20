#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run ./scripts/configure.sh first" >&2; exit 1; }
START="${TIINGO_START_DATE:-$(grep '^TIINGO_START_DATE=' .env | tail -1 | cut -d= -f2-)}"
START="${START:-2014-01-01}"
END="$(date +%F)"
FULL="--full"
SYMBOLS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --full) FULL="--full"; shift ;;
    --incremental) FULL=""; shift ;;
    --start) START="$2"; shift 2 ;;
    --end) END="$2"; shift 2 ;;
    --symbols) SYMBOLS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
TOKEN="$(grep '^TIINGO_API_TOKEN=' .env | tail -1 | cut -d= -f2-)"
[[ -n "$TOKEN" && "$TOKEN" != replace-* ]] || { echo "Configure TIINGO_API_TOKEN first" >&2; exit 1; }
docker compose --env-file .env build backtest-runtime
docker compose --env-file .env stop backtest-runtime || true
ARGS=(compose --env-file .env run --rm --no-deps --entrypoint python backtest-runtime
  /app/tools/sync_tiingo_data.py
  --universe /app/config/universe_whitelist_v1.0.json
  --data-root /data/lean --start "$START" --end "$END")
[[ -n "$FULL" ]] && ARGS+=(--full)
[[ -n "$SYMBOLS" ]] && ARGS+=(--symbols "$SYMBOLS")
if ! docker "${ARGS[@]}"; then
  echo "Data synchronization failed. The API container remains stopped." >&2
  exit 2
fi
docker compose --env-file .env up -d backtest-runtime
./scripts/data-status.sh --wait
echo "ALPHAFORGE_REAL_DATA_READY"
