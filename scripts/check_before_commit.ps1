$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "[1/4] Validate Local LEAN Runtime package"
python .\lean_worker\validate_package.py

Write-Host "[2/4] Ensure no real-data ZIP files are staged"
$forbidden = git diff --cached --name-only | Where-Object {
    $_ -match '^lean_worker/workspace/(data|results|jobs|models|service|locks|backups)/' -and $_ -notmatch '\.gitkeep$'
}
if ($forbidden) {
    $forbidden | ForEach-Object { Write-Host "FORBIDDEN: $_" }
    throw "Generated/runtime workspace files must not be committed."
}

Write-Host "[3/4] Show staged files"
git diff --cached --stat

Write-Host "[4/4] Show repository status"
git status --short
