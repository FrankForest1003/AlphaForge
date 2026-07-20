[CmdletBinding()]
param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path $RepoPath).Path
$target = Join-Path $repo ".gitignore"
$snippet = Join-Path $repo ".gitignore.alphaforge.snippet"

if (-not (Test-Path $snippet)) {
    throw "Missing snippet: $snippet"
}

if (-not (Test-Path $target)) {
    New-Item -ItemType File -Path $target | Out-Null
}

$marker = "# BEGIN ALPHAFORGE GENERATED IGNORE RULES"
$current = Get-Content $target -Raw -ErrorAction SilentlyContinue
if ($null -eq $current) { $current = "" }

if ($current.Contains($marker)) {
    Write-Host "AlphaForge ignore rules already exist; no changes made."
    exit 0
}

$rules = Get-Content $snippet -Raw
Add-Content -Path $target -Value "`n$marker`n$rules`n# END ALPHAFORGE GENERATED IGNORE RULES`n"
Write-Host "Updated $target"
