#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ARCHIVE="${1:-}"
FORCE="${2:-}"
[[ -f "$ARCHIVE" ]] || { echo "Usage: ./scripts/restore.sh BACKUP.tar.gz --force" >&2; exit 2; }
[[ "$FORCE" == "--force" ]] || { echo "Restore overwrites workspace data. Add --force." >&2; exit 2; }
docker compose --env-file .env down --remove-orphans || true
rm -rf workspace/{data,results,models,service}
tar -xzf "$ARCHIVE"
docker compose --env-file .env up -d backtest-runtime
echo "ALPHAFORGE_BACKUP_RESTORED"
