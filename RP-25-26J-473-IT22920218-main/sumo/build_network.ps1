# SUMO Network Build Script
# Run this after installing SUMO to generate junction.net.xml

Write-Host "Building SUMO network from node/edge files..." -ForegroundColor Green

# Check if SUMO is installed
if (-not (Get-Command netconvert -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: SUMO is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install SUMO from: https://www.eclipse.org/sumo/" -ForegroundColor Yellow
    Write-Host "And add SUMO bin folder to your PATH" -ForegroundColor Yellow
    exit 1
}

# Build network
netconvert --node-files=junction.nod.xml --edge-files=junction.edg.xml --output-file=junction.net.xml --no-turnarounds

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Network built successfully: junction.net.xml" -ForegroundColor Green
} else {
    Write-Host "✗ Network build failed" -ForegroundColor Red
    exit 1
}
