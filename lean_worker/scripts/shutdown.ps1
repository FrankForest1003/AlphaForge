$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (Test-Path .env) { docker compose --env-file .env down --remove-orphans } else { docker compose down --remove-orphans }
Write-Host "ALPHAFORGE_LOCAL_RUNTIME_SHUT_DOWN"
