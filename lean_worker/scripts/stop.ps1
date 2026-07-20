$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (Test-Path .env) { docker compose --env-file .env stop } else { docker compose stop }
Write-Host "ALPHAFORGE_LOCAL_RUNTIME_STOPPED"
