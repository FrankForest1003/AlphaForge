$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path .env)) { throw "Run .\scripts\configure.ps1 first." }
$Lines = Get-Content .env
$Port = (($Lines | Where-Object { $_ -match '^ALPHAFORGE_PORT=' } | Select-Object -Last 1).Split('=',2)[1]).Trim()
$Token = (($Lines | Where-Object { $_ -match '^ALPHAFORGE_API_TOKEN=' } | Select-Object -Last 1).Split('=',2)[1]).Trim()
Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/data/status" -Headers @{"X-Worker-Token"=$Token} | ConvertTo-Json -Depth 30
