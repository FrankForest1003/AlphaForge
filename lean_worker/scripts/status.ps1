$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path .env)) { throw "Run .\scripts\configure.ps1 first." }
$Lines = Get-Content .env
function Read-Env([string]$Name,[string]$Default="") {
    $Line = $Lines | Where-Object { $_ -match ('^' + [Regex]::Escape($Name) + '=') } | Select-Object -Last 1
    if ($Line) { return $Line.Split('=',2)[1].Trim() }
    return $Default
}
$Port = Read-Env "ALPHAFORGE_PORT" "18081"
$Token = Read-Env "ALPHAFORGE_API_TOKEN"
docker compose --env-file .env ps
try {
    Write-Host "`nHealth:"
    Invoke-RestMethod "http://127.0.0.1:$Port/health" | ConvertTo-Json -Depth 10
    Write-Host "`nData:"
    Invoke-RestMethod "http://127.0.0.1:$Port/v1/data/status" -Headers @{"X-Worker-Token"=$Token} | ConvertTo-Json -Depth 20
} catch {
    Write-Warning $_.Exception.Message
}
