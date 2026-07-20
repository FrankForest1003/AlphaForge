$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path .env)) { throw "Run .\scripts\configure.ps1 first." }
docker compose --env-file .env restart backtest-runtime
Write-Host "ALPHAFORGE_LOCAL_RUNTIME_RESTARTED"
