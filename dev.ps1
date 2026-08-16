<#
# Data Insight Platform Dev Startup Script
# Infrastructure (PostgreSQL/Redis/MinIO/ClickHouse/Celery) runs in Docker
# Backend API (with hot reload) and Frontend/Admin run as local processes
# Usage: .\dev.ps1
# Stop: Ctrl+C (auto stops all processes)
#>

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($root)) { $root = (Get-Location).Path }

# Check if running in project root
if (-not (Test-Path (Join-Path $root "docker-compose.yml"))) {
    Write-Host "Error: please run this script in project root directory" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Data Insight Platform Dev Startup ===" -ForegroundColor Cyan
Write-Host "Project root: $root"
Write-Host ""

# 1. Start Docker infrastructure (skip backend/frontend)
Write-Host "1. Starting Docker infrastructure (PostgreSQL/Redis/MinIO/ClickHouse/Celery)..." -ForegroundColor Green
Push-Location $root
docker-compose up -d postgres redis clickhouse minio celery-worker
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Docker startup failed, please check if Docker is running" -ForegroundColor Red
    exit 1
}
Pop-Location

Write-Host "Waiting for infrastructure to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 8

# 2. Determine Python command (prefer project venv)
$pythonCmd = "python"
if (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) {
    Write-Host "Using project virtual environment"
    $pythonCmd = Join-Path $root ".venv\Scripts\python.exe"
}

$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"

# 3. Start Backend API (uvicorn with hot reload), in separate window
Write-Host ""
Write-Host "2. Starting Backend API (uvicorn hot reload, port 8000)..." -ForegroundColor Green
Start-Process -FilePath $pythonCmd -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--reload" -WorkingDirectory $backendDir -WindowStyle Normal

# 4. Start Frontend (user, port 5173), in separate window
Write-Host "3. Starting Frontend (user, port 5173)..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","npm run dev" -WorkingDirectory $frontendDir -WindowStyle Normal

# 5. Start Admin (port 5174), in separate window
Write-Host "4. Starting Admin (port 5174)..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","npm run dev:admin" -WorkingDirectory $frontendDir -WindowStyle Normal

# 6. Start Celery Worker hot reload watcher (separate window)
Write-Host "5. Starting Celery Worker hot reload watcher..." -ForegroundColor Green
$watchScript = Join-Path $root "watch-celery.ps1"
if (Test-Path $watchScript) {
    Start-Process -FilePath "powershell.exe" -ArgumentList "-ExecutionPolicy","Bypass","-File",$watchScript -WorkingDirectory $root -WindowStyle Normal
}
else {
    Write-Host "  Warning: watch-celery.ps1 not found, skip hot reload watcher" -ForegroundColor Yellow
}

# Wait for services to be ready
Write-Host ""
Write-Host "Waiting for services to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 8

# 7. Show running status
Write-Host ""
Write-Host "=== All Services Started ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Access URLs:"
Write-Host "  User UI:        http://localhost:5173"
Write-Host "  Admin:          http://localhost:5174/"
Write-Host "  Backend API:    http://localhost:8000/docs (Swagger)"
Write-Host "  MinIO Console:  http://localhost:9001"
Write-Host ""
Write-Host "Hot Reload Features:"
Write-Host "  Backend code:   uvicorn auto restart (Python)"
Write-Host "  Celery code:    watch-celery.ps1 auto restart celery-worker + backend containers (2s after .py save)"
Write-Host "  Frontend code:  Vite HMR (Vue/JS/CSS), no browser refresh needed"
Write-Host "  Admin code:     same HMR"
Write-Host ""
Write-Host "Stop services:"
Write-Host "  Press Ctrl+C to stop all background processes" -ForegroundColor Yellow
Write-Host ""

# Stop process by port
function Stop-ByPort {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if ($conn) {
            $conn.OwningProcess | Sort-Object -Unique | ForEach-Object {
                Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# Cleanup function
function Cleanup {
    Write-Host ""
    Write-Host "Stopping all services..." -ForegroundColor Yellow
    Stop-ByPort -Ports @(8000, 5173, 5174)
    Write-Host "All background processes stopped" -ForegroundColor Green
}

# Register process exit event (Ctrl+C / close window auto cleanup)
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Stop-ByPort -Ports @(8000, 5173, 5174)
}

try {
    # Keep script running
    while ($true) {
        Start-Sleep -Seconds 3600
    }
}
finally {
    Cleanup
}
