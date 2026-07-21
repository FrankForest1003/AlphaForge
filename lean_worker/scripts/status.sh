#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
docker compose --env-file .env ps
PORT="$(grep '^ALPHAFORGE_PORT=' .env | tail -1 | cut -d= -f2-)"
TOKEN="$(grep '^ALPHAFORGE_API_TOKEN=' .env | tail -1 | cut -d= -f2-)"
echo "Health:"
curl -fsS "http://127.0.0.1:${PORT}/health" | python3 -m json.tool
echo "Data:"
curl -fsS -H "X-Worker-Token: ${TOKEN}" "http://127.0.0.1:${PORT}/v1/data/status" | python3 -m json.tool
