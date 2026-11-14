#requires -Version 5.1
[CmdletBinding()]
param([string]$FrontendOrigin = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envPath = Join-Path $projectRoot '.env'
if ($FrontendOrigin) {
    $uri = [Uri]$FrontendOrigin
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) {
        throw 'FrontendOrigin must be the exact HTTPS frontend origin without a path or credentials.'
    }
    $FrontendOrigin = $uri.GetLeftPart([UriPartial]::Authority)
}
$lines = if (Test-Path -LiteralPath $envPath) { @(Get-Content -LiteralPath $envPath) } else { @() }
if (-not ($lines | Where-Object { $_ -match '^ARTAUD_API_KEY=.+$' })) {
    $bytes = New-Object byte[] 36
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    $key = [Convert]::ToBase64String($bytes)
    $lines = @($lines | Where-Object { $_ -notmatch '^ARTAUD_API_KEY=' }) + "ARTAUD_API_KEY=$key"
}
if ($FrontendOrigin) {
    $lines = @($lines | Where-Object { $_ -notmatch '^ARTAUD_ALLOWED_ORIGINS=' }) + "ARTAUD_ALLOWED_ORIGINS=$FrontendOrigin"
}
[IO.File]::WriteAllLines($envPath, $lines, (New-Object Text.UTF8Encoding($false)))
Write-Host 'Owner key configured in the ignored .env file. Existing settings were preserved.'
Write-Host 'Keep the key private. Enter it in the frontend Connection settings; never put it in Vercel build variables.'
Write-Host 'Start with: .\scripts\Start-Artaud.ps1 -DemoControls'
