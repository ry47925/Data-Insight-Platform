<#
# Celery Worker + Backend Hot Reload Watcher
# Watches backend/app directory for .py file changes, auto restarts Docker
# data-insight-celery and data-insight-backend containers
# Usage: .\watch-celery.ps1
# Stop: Ctrl+C
#
# Principle:
#   Docker volume mounts ./backend/app:/app/app, code changes sync to containers in real-time
#   But Celery/uvicorn processes do not auto-reload, need to restart containers to reload code
#   This script polls .py file LastWriteTime, debounces and restarts both containers
#   (backend 容器 uvicorn 无 --reload，改代码后必须重启容器才能生效，故一并处理)
#>

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($root)) { $root = (Get-Location).Path }

$watchPath = Join-Path $root "backend\app"

if (-not (Test-Path $watchPath)) {
    Write-Host "Error: watch path not found $watchPath" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Celery + Backend Hot Reload ===" -ForegroundColor Cyan
Write-Host "Watch path: $watchPath"
Write-Host "Target containers: data-insight-celery + data-insight-backend"
Write-Host "Trigger: .py file change (on save)"
Write-Host "Debounce: 2 seconds (avoid multiple restarts on consecutive saves)"
Write-Host ""
Write-Host "Press Ctrl+C to stop"
Write-Host "" -ForegroundColor Yellow

# Record initial LastWriteTime for all .py files
Write-Host "Scanning initial file state..." -ForegroundColor Cyan
$fileState = @{}
Get-ChildItem -Path $watchPath -Filter "*.py" -Recurse -File | ForEach-Object {
    $fileState[$_.FullName] = $_.LastWriteTime
}
Write-Host "Recorded $($fileState.Count) .py files" -ForegroundColor Green

$lastTrigger = [DateTime]::MinValue
$debounceMs = 2000

Write-Host "Watcher started, waiting for code changes..." -ForegroundColor Green

try {
    while ($true) {
        Start-Sleep -Milliseconds 800

        $now = Get-Date
        $diff = ($now - $lastTrigger).TotalMilliseconds
        if ($diff -lt $debounceMs) {
            continue
        }

        $changedFiles = @()

        # Scan all current .py files
        $currentFiles = Get-ChildItem -Path $watchPath -Filter "*.py" -Recurse -File
        foreach ($file in $currentFiles) {
            $path = $file.FullName
            if ($fileState.ContainsKey($path)) {
                if ($file.LastWriteTime -ne $fileState[$path]) {
                    $changedFiles += $file.Name
                    $fileState[$path] = $file.LastWriteTime
                }
            }
            else {
                # New file
                $changedFiles += $file.Name
                $fileState[$path] = $file.LastWriteTime
            }
        }

        if ($changedFiles.Count -eq 0) {
            continue
        }

        $lastTrigger = $now
        $timestamp = $now.ToString("HH:mm:ss")

        if ($changedFiles.Count -eq 1) {
            Write-Host "[$timestamp] Change detected: $($changedFiles[0])" -ForegroundColor Yellow
        }
        else {
            Write-Host "[$timestamp] $($changedFiles.Count) files changed, last: $($changedFiles[-1])" -ForegroundColor Yellow
        }
        Write-Host "[$timestamp] Restarting celery-worker + backend containers..." -ForegroundColor Cyan

        # Restart Docker containers
        # docker-compose outputs warnings to stderr, temporarily relax error action
        $ErrorActionPreference = "Continue"
        $restartResult = docker-compose restart celery-worker backend 2>&1
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($exitCode -eq 0) {
            Start-Sleep -Seconds 3
            $timestamp2 = (Get-Date).ToString("HH:mm:ss")
            Write-Host "[$timestamp2] containers restarted, code reloaded" -ForegroundColor Green
        }
        else {
            $timestamp2 = (Get-Date).ToString("HH:mm:ss")
            Write-Host "[$timestamp2] Restart failed: $restartResult" -ForegroundColor Red
        }
    }
}
finally {
    Write-Host ""
    Write-Host "Watcher stopped" -ForegroundColor Yellow
}
