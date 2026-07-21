#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
docker compose --env-file .env restart backtest-runtime
echo "ALPHAFORGE_LOCAL_RUNTIME_RESTARTED"
