#requires -Version 5.1
<# Start the existing local stack. Project volumes and teammate-owned configuration are preserved. #>
[CmdletBinding()]
param([switch]$RebuildFrontend)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install Docker Desktop and start its Linux engine, then run this script again.'
    }
    docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with its Linux engine, then run this script again.' }

    if ($RebuildFrontend) {
        if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
            throw 'Install a current Node.js LTS release to rebuild the frontend. The committed build runs without Node.'
        }
        Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
        try {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed. Correct the reported errors and retry.' }
        } finally { Pop-Location }
    }

    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'The local stack could not start. Check the Docker output above.' }

    $health = $null
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://localhost:8000/health' -TimeoutSec 2
            break
        } catch {
            if ($attempt -eq 39) { throw 'The controller did not become reachable. Run docker compose logs controller to inspect the cause.' }
            Start-Sleep -Milliseconds 500
        }
    }
    $index = Invoke-WebRequest -Uri 'http://localhost:8000/' -UseBasicParsing -TimeoutSec 5
    if ($index.StatusCode -ne 200) { throw 'The dashboard build is unavailable. Retry with -RebuildFrontend.' }
    $overview = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/overview' -TimeoutSec 5
    Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/activity?after=0' -TimeoutSec 5 | Out-Null

    Write-Host ''
    Write-Host 'Artaud is running: http://localhost:8000/' -ForegroundColor Green
    Write-Host ("Storage nodes: {0} registered, {1} available." -f $overview.worker_count, $overview.available_workers)
    if (-not $health.recovery_available) {
        Write-Host 'Recovery service is pending Member B integration. Registered nodes remain Joining until inventory verification.' -ForegroundColor DarkYellow
    }
    Write-Host 'Choose Cluster to see connections, chunk placement, recovery observations and recent transfers.'
    Write-Host 'Stop with docker compose down to keep stored data.'
} finally { Pop-Location }
