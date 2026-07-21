param([string]$OutputFile)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) { throw "tar.exe is required." }
if (-not $OutputFile) {
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputFile = Join-Path $Root "workspace\backups\alphaforge-backup-$Stamp.tar.gz"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputFile) | Out-Null
$WasRunning = $false
if (Test-Path .env) {
    $Running = docker compose --env-file .env ps --status running --services
    $WasRunning = $Running -contains "backtest-runtime"
    if ($WasRunning) { docker compose --env-file .env stop backtest-runtime | Out-Host }
}
try {
    tar.exe -czf $OutputFile workspace/data workspace/results workspace/models workspace/service
    if ($LASTEXITCODE -ne 0) { throw "Backup tar command failed." }
} finally {
    if ($WasRunning) { docker compose --env-file .env start backtest-runtime | Out-Host }
}
Write-Host "Backup created: $OutputFile"
Write-Host "The .env file and API tokens are intentionally not included."
Write-Host "ALPHAFORGE_BACKUP_CREATED"
