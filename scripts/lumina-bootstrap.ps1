$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "> Starting LUMINA development services" -ForegroundColor Cyan
docker compose -f docker-compose.dev.yml up -d
if ($LASTEXITCODE -ne 0) { throw "Docker services failed" }

$models = ollama list
if ($models -notmatch "nomic-embed-text") {
  Write-Host "> Pulling nomic-embed-text" -ForegroundColor Cyan
  ollama pull nomic-embed-text
  if ($LASTEXITCODE -ne 0) { throw "Embedding model installation failed" }
}

Write-Host "> Building repository memory" -ForegroundColor Cyan
python scripts/ai/index_repository.py
if ($LASTEXITCODE -ne 0) { throw "Repository indexing failed" }

& "$PSScriptRoot\lumina-baseline.ps1"
if ($LASTEXITCODE -ne 0) { throw "Baseline generation failed" }

Write-Host "LUMINA_ACCELERATION_PHASE3_READY" -ForegroundColor Green
