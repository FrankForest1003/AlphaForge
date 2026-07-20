param(
    [string]$StrategyId = "classic_30_stock_top3_momentum_v1",
    [string]$Symbols = "",
    [int]$TimeoutSeconds = 3600
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Lines = Get-Content .env
function Read-Env([string]$Name,[string]$Default="") {
    $Line = $Lines | Where-Object { $_ -match ('^' + [Regex]::Escape($Name) + '=') } | Select-Object -Last 1
    if ($Line) { return $Line.Split('=',2)[1].Trim() }
    return $Default
}
$Port = Read-Env "ALPHAFORGE_PORT" "18081"
$Token = Read-Env "ALPHAFORGE_API_TOKEN"
$Parameters = @{}
if ($Symbols) { $Parameters["symbols"] = $Symbols }
$Body = @{strategy_id=$StrategyId; parameters=$Parameters; timeout_seconds=$TimeoutSeconds} | ConvertTo-Json -Depth 10
$Job = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/v1/jobs" -Headers @{"X-Worker-Token"=$Token} -ContentType "application/json" -Body $Body
$RunId = $Job.run_id
$Job | ConvertTo-Json -Depth 10
while ($true) {
    $Status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/jobs/$RunId" -Headers @{"X-Worker-Token"=$Token}
    Write-Host "$(Get-Date -Format HH:mm:ss) state=$($Status.state)"
    if ($Status.state -eq "completed") { break }
    if ($Status.state -in @("failed","timeout","completed_with_data_gaps")) {
        $Status | ConvertTo-Json -Depth 20
        throw "Backtest did not complete successfully."
    }
    Start-Sleep -Seconds 3
}
$Output = Join-Path $PWD "workspace\results\$RunId\result.json"
Write-Host "Result: $Output"
Get-Content $Output -Raw | ConvertFrom-Json | Select-Object status,summary | ConvertTo-Json -Depth 20
