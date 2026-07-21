param(
    [switch]$Full,
    [switch]$Incremental,
    [string]$StartDate,
    [string]$EndDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$Symbols
)
$ErrorActionPreference = "Stop"
if ($Full -and $Incremental) { throw "Use either -Full or -Incremental, not both." }
$UseFull = $Full -or (-not $Incremental)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path .env)) { throw "Run .\scripts\configure.ps1 first." }
$EnvLines = Get-Content .env
function Read-Env([string]$Name, [string]$Default = "") {
    $Line = $EnvLines | Where-Object { $_ -match ('^' + [Regex]::Escape($Name) + '=') } | Select-Object -Last 1
    if ($Line) { return $Line.Split('=', 2)[1].Trim() }
    return $Default
}
$Token = Read-Env "TIINGO_API_TOKEN"
if ([string]::IsNullOrWhiteSpace($Token) -or $Token -like "replace-*") {
    throw "TIINGO_API_TOKEN is not configured. Run .\scripts\configure.ps1 again."
}
if (-not $StartDate) { $StartDate = Read-Env "TIINGO_START_DATE" "2014-01-01" }
docker info | Out-Null
Write-Host "Ensuring the runtime image is built..."
docker compose --env-file .env build backtest-runtime | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Docker image build failed." }
Write-Host "Stopping the API container while market data is updated..."
docker compose --env-file .env stop backtest-runtime | Out-Host
$DockerArgs = @(
    "compose", "--env-file", ".env", "run", "--rm", "--no-deps",
    "--entrypoint", "python", "backtest-runtime",
    "/app/tools/sync_tiingo_data.py",
    "--universe", "/app/config/universe_whitelist_v1.0.json",
    "--data-root", "/data/lean",
    "--start", $StartDate,
    "--end", $EndDate
)
if ($UseFull) { $DockerArgs += "--full" }
if ($Symbols) { $DockerArgs += @("--symbols", $Symbols) }
& docker @DockerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Data synchronization failed. The API container remains stopped to avoid using a partial update."
}
Write-Host "Starting the API container with the updated dataset..."
docker compose --env-file .env up -d backtest-runtime | Out-Host
$Port = Read-Env "ALPHAFORGE_PORT" "18081"
$ApiToken = Read-Env "ALPHAFORGE_API_TOKEN"
for ($i = 0; $i -lt 60; $i++) {
    try {
        $Status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/data/status" -Headers @{"X-Worker-Token"=$ApiToken} -TimeoutSec 5
        $Status | ConvertTo-Json -Depth 20
        if ($Status.ready) {
            Write-Host "ALPHAFORGE_REAL_DATA_READY"
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds 2
}
throw "The service restarted, but the dataset did not report ready. Run .\scripts\data-status.ps1 and inspect workspace\data\lean\alphaforge-catalog."
