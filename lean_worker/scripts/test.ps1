param(
    [string]$Strategies = "classic_30_stock_top3_momentum_v1,ml_30_stock_gradient_boosting_v1",
    [int]$TimeoutSeconds = 3600
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path .env)) { throw "Run .\scripts\configure.ps1 first." }
$TokenLine = Get-Content .env | Where-Object { $_ -match '^ALPHAFORGE_API_TOKEN=' } | Select-Object -Last 1
$Token = if ($TokenLine) { $TokenLine.Split('=', 2)[1].Trim() } else { "" }
if (-not $Token) { throw "ALPHAFORGE_API_TOKEN is missing from .env" }
docker compose --env-file .env exec -T backtest-runtime `
    python /app/client/smoke_test.py `
    --base-url http://127.0.0.1:8081 `
    --token $Token `
    --strategies $Strategies `
    --timeout-seconds $TimeoutSeconds
