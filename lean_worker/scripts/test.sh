#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run ./scripts/configure.sh first" >&2; exit 1; }
TOKEN="$(grep '^ALPHAFORGE_API_TOKEN=' .env | tail -1 | cut -d= -f2-)"
STRATEGIES="${1:-classic_30_stock_top3_momentum_v1,ml_30_stock_gradient_boosting_v1}"
TIMEOUT_SECONDS="${2:-3600}"
docker compose --env-file .env exec -T backtest-runtime \
  python /app/client/smoke_test.py \
  --base-url http://127.0.0.1:8081 \
  --token "$TOKEN" \
  --strategies "$STRATEGIES" \
  --timeout-seconds "$TIMEOUT_SECONDS"
