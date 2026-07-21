param(
    [string]$TiingoToken,
    [int]$Port = 18081,
    [switch]$SkipTiingo
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Convert-SecureStringToPlainText([Security.SecureString]$Secure) {
    $Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }
}

function Set-EnvValue([string]$Text, [string]$Name, [string]$Value) {
    $Pattern = "(?m)^" + [Regex]::Escape($Name) + "=.*$"
    $Line = "$Name=$Value"
    if ([Regex]::IsMatch($Text, $Pattern)) {
        return [Regex]::Replace($Text, $Pattern, $Line)
    }
    return $Text.TrimEnd() + "`n" + $Line + "`n"
}

if (Test-Path .env) {
    $EnvText = [IO.File]::ReadAllText((Resolve-Path .env))
} else {
    $EnvText = [IO.File]::ReadAllText((Resolve-Path .env.example))
}

$Bytes = New-Object byte[] 32
$Rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
$LocalToken = -join ($Bytes | ForEach-Object { $_.ToString("x2") })

if (-not $SkipTiingo -and -not $TiingoToken) {
    $SecureToken = Read-Host "Enter your own Tiingo API token (input is hidden)" -AsSecureString
    $TiingoToken = Convert-SecureStringToPlainText $SecureToken
}
if (-not $SkipTiingo -and [string]::IsNullOrWhiteSpace($TiingoToken)) {
    throw "Tiingo token is empty. Use -SkipTiingo only when you intentionally want to configure it later."
}

$EnvText = Set-EnvValue $EnvText "ALPHAFORGE_PORT" ([string]$Port)
$EnvText = Set-EnvValue $EnvText "ALPHAFORGE_API_TOKEN" $LocalToken
$EnvText = Set-EnvValue $EnvText "RUNTIME_VERSION" "1.1.3"
$EnvText = Set-EnvValue $EnvText "LEAN_REF" "0269115d3cfbf691c7a0b7cfcc9ed412cafb91f6"
$EnvText = Set-EnvValue $EnvText "TIINGO_START_DATE" "2014-01-01"
$EnvText = Set-EnvValue $EnvText "ALPHAFORGE_AUTO_GENERATE_SAMPLE_DATA" "false"
if (-not $SkipTiingo) {
    $EnvText = Set-EnvValue $EnvText "TIINGO_API_TOKEN" $TiingoToken.Trim()
}

[IO.File]::WriteAllText(
    (Join-Path $Root ".env"),
    $EnvText.TrimEnd() + "`n",
    (New-Object Text.UTF8Encoding($false))
)

@("data", "results", "jobs", "service", "models", "locks", "backups") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path "workspace" $_) | Out-Null
}

Write-Host "Configuration written to .env"
Write-Host "Local API port: $Port"
Write-Host "The API token and Tiingo token were not printed."
Write-Host "ALPHAFORGE_CONFIGURATION_READY"
