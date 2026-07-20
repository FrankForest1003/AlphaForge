#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT="${1:-workspace/backups/alphaforge-backup-${STAMP}.tar.gz}"
mkdir -p "$(dirname "$OUTPUT")"
WAS_RUNNING=false
if docker compose --env-file .env ps --status running --services | grep -qx backtest-runtime; then
  WAS_RUNNING=true
  docker compose --env-file .env stop backtest-runtime
fi
trap '$WAS_RUNNING && docker compose --env-file .env start backtest-runtime >/dev/null || true' EXIT
tar -czf "$OUTPUT" workspace/data workspace/results workspace/models workspace/service
$WAS_RUNNING && docker compose --env-file .env start backtest-runtime >/dev/null
trap - EXIT
echo "Backup created: $OUTPUT"
echo "The .env file and API tokens are intentionally not included."
echo "ALPHAFORGE_BACKUP_CREATED"
