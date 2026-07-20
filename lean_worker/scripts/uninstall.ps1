param(
    [switch]$RemoveImage,
    [switch]$RemoveData,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if ($RemoveData -and -not $Force) {
    throw "-RemoveData permanently deletes downloaded market data and all results. Add -Force after making a backup."
}
$Version = "1.1.3"
if (Test-Path .env) {
    $Line = Get-Content .env | Where-Object { $_ -match '^RUNTIME_VERSION=' } | Select-Object -Last 1
    if ($Line) { $Version = $Line.Split('=',2)[1].Trim() }
    docker compose --env-file .env down --remove-orphans
} else {
    docker compose down --remove-orphans
}
if ($RemoveImage) {
    docker image rm "alphaforge/local-lean-runtime:$Version" 2>$null
}
if ($RemoveData) {
    @("data", "results", "jobs", "service", "models", "locks") | ForEach-Object {
        $Path = Join-Path "workspace" $_
        if (Test-Path $Path) { Remove-Item -Recurse -Force $Path }
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}
Write-Host "ALPHAFORGE_LOCAL_RUNTIME_UNINSTALLED"
