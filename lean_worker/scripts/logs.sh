#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then docker compose --env-file .env logs -f --tail=200; else docker compose logs -f --tail=200; fi
