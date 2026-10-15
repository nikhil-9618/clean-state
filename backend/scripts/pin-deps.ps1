#!/usr/bin/env pwsh
# Windows/PowerShell twin of pin-deps.sh (regenerate requirements.lock.txt).
# Usage:  pwsh backend/scripts/pin-deps.ps1
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
$imageTag = "cleanslate-lock:local"

Write-Host "==> building lock stage"
docker build --target lock -t $imageTag .

Write-Host "==> extracting requirements.lock.txt"
$containerId = docker create $imageTag
try {
    docker cp "${containerId}:/tmp/requirements.lock.txt" ./requirements.lock.txt
} finally {
    docker rm -f $containerId | Out-Null
}

Write-Host "==> requirements.lock.txt"
Get-Content ./requirements.lock.txt

Write-Host ""
Write-Host "Next: rebuild the runtime image:"
Write-Host "  docker build -t cleanslate-api:local ./backend"
