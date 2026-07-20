#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${1:-18081}"
[[ -f .env ]] || cp .env.example .env

set_env() {
  local key="$1" value="$2"
  python3 - "$key" "$value" <<'PY'
from pathlib import Path
import sys
path=Path('.env')
key,value=sys.argv[1],sys.argv[2]
lines=path.read_text(encoding='utf-8-sig').splitlines()
out=[]
found=False
for line in lines:
    if line.startswith(key+'='):
        out.append(f'{key}={value}')
        found=True
    else:
        out.append(line)
if not found:
    out.append(f'{key}={value}')
path.write_text('\n'.join(out).rstrip()+'\n', encoding='utf-8')
PY
}

printf 'Enter your own Tiingo API token (input is hidden): '
IFS= read -r -s TIINGO_TOKEN
echo
[[ -n "$TIINGO_TOKEN" ]] || { echo "Tiingo token must not be empty" >&2; exit 1; }
LOCAL_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
set_env ALPHAFORGE_PORT "$PORT"
set_env ALPHAFORGE_API_TOKEN "$LOCAL_TOKEN"
set_env RUNTIME_VERSION 1.1.3
set_env LEAN_REF 0269115d3cfbf691c7a0b7cfcc9ed412cafb91f6
set_env TIINGO_API_TOKEN "$TIINGO_TOKEN"
set_env TIINGO_START_DATE 2014-01-01
set_env ALPHAFORGE_AUTO_GENERATE_SAMPLE_DATA false
mkdir -p workspace/{data,results,jobs,service,models,locks,backups}
echo "Configuration written to .env"
echo "The API token and Tiingo token were not printed."
echo "ALPHAFORGE_CONFIGURATION_READY"
