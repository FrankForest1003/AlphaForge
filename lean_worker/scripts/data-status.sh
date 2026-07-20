#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
WAIT=false
[[ "${1:-}" == "--wait" ]] && WAIT=true
PORT="$(grep '^ALPHAFORGE_PORT=' .env | tail -1 | cut -d= -f2-)"
TOKEN="$(grep '^ALPHAFORGE_API_TOKEN=' .env | tail -1 | cut -d= -f2-)"
for _ in $(seq 1 60); do
  if RESPONSE="$(curl -fsS -H "X-Worker-Token: ${TOKEN}" "http://127.0.0.1:${PORT}/v1/data/status")"; then
    python3 -m json.tool <<<"$RESPONSE"
    READY="$(python3 -c 'import json,sys; print(str(json.load(sys.stdin).get("ready",False)).lower())' <<<"$RESPONSE")"
    [[ "$READY" == true ]] && exit 0
    $WAIT || exit 1
  fi
  $WAIT || exit 1
  sleep 2
done
exit 1
