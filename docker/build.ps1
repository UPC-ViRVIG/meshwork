#!/usr/bin/env pwsh
# docker/build.ps1

$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host @"
Usage: .\build.ps1 [OPTIONS] [SERVICES]

Build MeshWork services

OPTIONS:
    --clean              Clean build (remove existing images)
    --pull               Pull latest base images first
    --help               Show this help

SERVICES (optional, default: all):
    blender              Blender service
    colmap               COLMAP service
    alicevision          AliceVision service

EXAMPLES:
    .\build.ps1                      Build all services (CPU mode)
    .\build.ps1 --clean              Clean build all services
    .\build.ps1 --pull               Pull latest and build all

    Set GPU=true in .env to enable GPU mode.

RUNTIME:
    docker compose up -d
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

"@
}

$DC = $null
try {
    docker compose version | Out-Null
    if ($LASTEXITCODE -eq 0) { $DC = "docker compose" }
} catch { }

if (-not $DC) {
    try {
        docker-compose version | Out-Null
        if ($LASTEXITCODE -eq 0) { $DC = "docker-compose" }
    } catch { }
}

if (-not $DC) {
    Write-Error "ERROR: Neither 'docker compose' nor 'docker-compose' found"
    exit 1
}

$EnvFile = if (Test-Path ".env") { ".env" } elseif (Test-Path ".env.example") { ".env.example" } else { $null }

if ($EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)\s*$') {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

$GPU = if ($env:GPU) { $env:GPU } else { "false" }

if ($GPU -eq "true") {
    $DCFiles = "-f docker-compose.yml -f docker-compose.gpu.yml"
} else {
    $DCFiles = "-f docker-compose.yml"
}

$Clean = $false
$Pull = $false
$Services = @()

$i = 0
while ($i -lt $args.Count) {
    switch ($args[$i]) {
        "--clean" {
            $Clean = $true
            $i++
        }
        "--pull" {
            $Pull = $true
            $i++
        }
        "--help" {
            Show-Help
            exit 0
        }
        { $_ -in @("blender", "colmap", "alicevision") } {
            $Services += $args[$i]
            $i++
        }
        default {
            Write-Error "Unknown option: $($args[$i])"
            Show-Help
            exit 1
        }
    }
}

if ($Services.Count -eq 0) {
    $Services = @("blender", "colmap", "alicevision")
}

$env:CUDA_VERSION = if ($env:CUDA_VERSION) { $env:CUDA_VERSION } else { "11.8.0" }
$env:COLMAP_TAG = if ($env:COLMAP_TAG) { $env:COLMAP_TAG } else { "latest" }
$env:ALICEVISION_TAG = if ($env:ALICEVISION_TAG) { $env:ALICEVISION_TAG } else { "3.2.0-ubuntu20.04-cuda11.3.1" }

Write-Host "Building MeshWork Services"
Write-Host "=========================="
Write-Host "Services to build: $($Services -join ', ')"
Write-Host "Using: $DC"
Write-Host "GPU mode: $GPU"
Write-Host ""

try {
    python -c "import grpc_tools" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "grpcio-tools not found" }
} catch {
    Write-Error "ERROR: grpcio-tools not found in current Python environment"
    Write-Host "Please install it: pip install grpcio-tools"
    exit 1
}

Write-Host "Stopping running containers..."
try {
    Invoke-Expression "$DC $DCFiles down" 2>$null
} catch { }
Start-Sleep -Seconds 1

Write-Host "Generating protobuf code..."
Set-Location "..\server"

Remove-Item -Path "meshwork_pb2.py", "meshwork_pb2_grpc.py" -ErrorAction SilentlyContinue

python -m grpc_tools.protoc --proto_path=. --python_out=. --grpc_python_out=. meshwork.proto

if (-not (Test-Path "meshwork_pb2.py") -or -not (Test-Path "meshwork_pb2_grpc.py")) {
    Write-Error "ERROR: Failed to generate protobuf files"
    exit 1
}
Write-Host "Generated: meshwork_pb2.py, meshwork_pb2_grpc.py"

Set-Location "..\docker"

Write-Host ""
Write-Host "Creating runtime directories..."

if (Test-Path "..\.runtime") {
    Remove-Item -Path "..\.runtime" -Recurse -Force
}

New-Item -ItemType Directory -Path "..\.runtime\socks" -Force | Out-Null
New-Item -ItemType Directory -Path "..\.runtime\logs" -Force | Out-Null
New-Item -ItemType Directory -Path "..\.runtime\workspace" -Force | Out-Null

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

if ($Pull) {
    Write-Host ""
    Write-Host "Pulling base images..."

    if ($Services -contains "blender") {
        docker pull "nvidia/cuda:$($env:CUDA_VERSION)-runtime-ubuntu22.04"
        if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to pull CUDA image - continuing with cached version" }
    }

    if ($Services -contains "colmap") {
        docker pull "colmap/colmap:$($env:COLMAP_TAG)"
        if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to pull COLMAP image - continuing with cached version" }
    }

    if ($Services -contains "alicevision") {
        docker pull "alicevision/alicevision:$($env:ALICEVISION_TAG)"
        if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to pull AliceVision image - continuing with cached version" }
    }

    Write-Host ""
}

if ($Clean) {
    Write-Host "Cleaning existing images..."
    foreach ($service in $Services) {
        switch ($service) {
            "blender"     { try { docker rmi "blender-service:latest" 2>$null } catch { } }
            "colmap"      { try { docker rmi "colmap-service:latest" 2>$null } catch { } }
            "alicevision" { try { docker rmi "alicevision-service:latest" 2>$null } catch { } }
        }
    }
    Write-Host ""
}

Write-Host "Building services..."
$buildStartTime = Get-Date

foreach ($service in $Services) {
    Write-Host "Building $service service..."
    $serviceStartTime = Get-Date

    try {
        switch ($service) {
            "blender"     { Invoke-Expression "$DC $DCFiles build blender-service" }
            "colmap"      { Invoke-Expression "$DC $DCFiles build colmap-service" }
            "alicevision" { Invoke-Expression "$DC $DCFiles build alicevision-service" }
        }
        if ($LASTEXITCODE -ne 0) { throw "Docker build failed for $service" }
    } catch {
        Write-Error "Failed to build $service service: $_"
        exit 1
    }

    $serviceEndTime = Get-Date
    $serviceDuration = [math]::Round(($serviceEndTime - $serviceStartTime).TotalSeconds)
    Write-Host "$service build completed in ${serviceDuration}s"
    Write-Host ""
}

$buildEndTime = Get-Date
$totalDuration = [math]::Round(($buildEndTime - $buildStartTime).TotalSeconds)

Write-Host "================================================================"
Write-Host "Build Summary"
Write-Host "================================================================"
Write-Host "Services built: $($Services -join ', ')"
Write-Host "GPU mode: $GPU"
Write-Host "Total build time: ${totalDuration}s"
Write-Host ""
if ($GPU -eq "true") {
    Write-Host "To start: $DC -f docker-compose.yml -f docker-compose.gpu.yml up -d"
} else {
    Write-Host "To start: $DC up -d"
}