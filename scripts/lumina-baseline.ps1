$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Output = Join-Path $Root "docs\generated"
New-Item -ItemType Directory -Force -Path $Output | Out-Null

Write-Host "> Generating architecture inventory" -ForegroundColor Cyan
python scripts/ai/architecture_inventory.py
if ($LASTEXITCODE -ne 0) { throw "Architecture inventory failed" }

Write-Host "> Capturing Ruff baseline" -ForegroundColor Cyan
ruff check backend launcher --output-format json | Out-File -Encoding utf8 "$Output\ruff-baseline.json"
$ruffExit = $LASTEXITCODE

Write-Host "> Capturing Git status" -ForegroundColor Cyan
git status --short | Out-File -Encoding utf8 "$Output\git-status-baseline.txt"

Write-Host "LUMINA_BASELINE_COMPLETE (ruff exit=$ruffExit)" -ForegroundColor Green
exit 0
