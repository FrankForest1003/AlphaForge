$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (Test-Path .env) { docker compose --env-file .env logs -f --tail=200 } else { docker compose logs -f --tail=200 }
