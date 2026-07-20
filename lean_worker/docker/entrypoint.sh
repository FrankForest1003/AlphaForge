#!/usr/bin/env bash
set -euo pipefail

mkdir -p \
  /data/lean \
  /runtime/results \
  /runtime/jobs \
  /runtime/service \
  /runtime/models \
  /runtime/locks

python /app/tools/prepare_local_data.py \
  --template-data /opt/lean-default-data \
  --data-root /data/lean \
  $(if [[ "${ALPHAFORGE_AUTO_GENERATE_SAMPLE_DATA:-true}" == "true" ]]; then echo --generate-sample; fi)

exec "$@"
