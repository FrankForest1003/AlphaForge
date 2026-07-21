#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STRATEGY="${1:-classic_30_stock_top3_momentum_v1}"
PORT="$(grep '^ALPHAFORGE_PORT=' .env | tail -1 | cut -d= -f2-)"
TOKEN="$(grep '^ALPHAFORGE_API_TOKEN=' .env | tail -1 | cut -d= -f2-)"
BODY="$(python3 - "$STRATEGY" <<'PY'
import json,sys
print(json.dumps({'strategy_id':sys.argv[1],'parameters':{},'timeout_seconds':3600}))
PY
)"
JOB="$(curl -fsS -X POST -H "X-Worker-Token: ${TOKEN}" -H 'Content-Type: application/json' -d "$BODY" "http://127.0.0.1:${PORT}/v1/jobs")"
echo "$JOB" | python3 -m json.tool
RUN_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' <<<"$JOB")"
while true; do
  STATUS="$(curl -fsS -H "X-Worker-Token: ${TOKEN}" "http://127.0.0.1:${PORT}/v1/jobs/${RUN_ID}")"
  STATE="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])' <<<"$STATUS")"
  echo "$(date +%H:%M:%S) state=$STATE"
  [[ "$STATE" == completed ]] && break
  if [[ "$STATE" == failed || "$STATE" == timeout || "$STATE" == completed_with_data_gaps ]]; then
    python3 -m json.tool <<<"$STATUS"
    exit 1
  fi
  sleep 3
done
echo "Result: workspace/results/${RUN_ID}/result.json"
