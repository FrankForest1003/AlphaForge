param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Force) { throw "Restore overwrites workspace data. Re-run with -Force." }
if (-not (Test-Path $Archive)) { throw "Backup archive not found: $Archive" }
if (Test-Path .env) { docker compose --env-file .env down --remove-orphans | Out-Host }
@("data","results","models","service") | ForEach-Object {
    $Path = Join-Path "workspace" $_
    if (Test-Path $Path) { Remove-Item -Recurse -Force $Path }
}
tar.exe -xzf $Archive
if ($LASTEXITCODE -ne 0) { throw "Restore tar command failed." }
if (Test-Path .env) { docker compose --env-file .env up -d backtest-runtime | Out-Host }
Write-Host "ALPHAFORGE_BACKUP_RESTORED"
