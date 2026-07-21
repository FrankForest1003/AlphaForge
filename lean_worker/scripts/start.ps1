$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is not installed or docker is not in PATH."
}
docker info | Out-Null
if (-not (Test-Path .env)) {
    throw "Configuration is missing. Run .\scripts\configure.ps1 first."
}
@("data", "results", "jobs", "service", "models", "locks", "backups") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path "workspace" $_) | Out-Null
}
docker compose --env-file .env up -d --build
$PortLine = Get-Content .env | Where-Object { $_ -match '^ALPHAFORGE_PORT=' } | Select-Object -First 1
$Port = if ($PortLine) { $PortLine.Split('=', 2)[1].Trim() } else { "18081" }
for ($i = 0; $i -lt 180; $i++) {
    try {
        $Health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 5
        if ($Health.status -eq "ok") {
            $Health | ConvertTo-Json -Depth 10
            Write-Host "Swagger: http://127.0.0.1:$Port/docs"
            Write-Host "ALPHAFORGE_LOCAL_RUNTIME_STARTED"
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds 2
}
throw "Runtime did not become healthy. Run .\scripts\logs.ps1"
