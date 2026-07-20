#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
REMOVE_IMAGE=false
REMOVE_DATA=false
FORCE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove-image) REMOVE_IMAGE=true ;;
    --remove-data) REMOVE_DATA=true ;;
    --force) FORCE=true ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
if $REMOVE_DATA && ! $FORCE; then
  echo "--remove-data is destructive. Add --force after making a backup." >&2
  exit 2
fi
VERSION="$(grep '^RUNTIME_VERSION=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
VERSION="${VERSION:-1.1.3}"
if [[ -f .env ]]; then docker compose --env-file .env down --remove-orphans; else docker compose down --remove-orphans; fi
$REMOVE_IMAGE && docker image rm "alphaforge/local-lean-runtime:${VERSION}" || true
if $REMOVE_DATA; then
  rm -rf workspace/{data,results,jobs,service,models,locks}
  mkdir -p workspace/{data,results,jobs,service,models,locks}
fi
echo "ALPHAFORGE_LOCAL_RUNTIME_UNINSTALLED"
