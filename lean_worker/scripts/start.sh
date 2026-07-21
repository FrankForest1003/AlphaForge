#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v docker >/dev/null || { echo "Docker Desktop is required" >&2; exit 1; }
docker info >/dev/null
[[ -f .env ]] || { echo "Run ./scripts/configure.sh first" >&2; exit 1; }
mkdir -p workspace/{data,results,jobs,service,models,locks,backups}
docker compose --env-file .env up -d --build
PORT="$(grep '^ALPHAFORGE_PORT=' .env | tail -1 | cut -d= -f2- || true)"
PORT="${PORT:-18081}"
for _ in $(seq 1 180); do
  if curl -fsS "http://127.0.0.1:${PORT}/health"; then
    echo
    echo "Swagger: http://127.0.0.1:${PORT}/docs"
    echo "ALPHAFORGE_LOCAL_RUNTIME_STARTED"
    exit 0
  fi
  sleep 2
done
echo "Runtime did not become healthy. Run ./scripts/logs.sh" >&2
exit 1
