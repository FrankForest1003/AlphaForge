#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then docker compose --env-file .env down --remove-orphans; else docker compose down --remove-orphans; fi
echo "ALPHAFORGE_LOCAL_RUNTIME_SHUT_DOWN"
