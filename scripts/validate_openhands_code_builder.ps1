$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host '=== LUMINA OpenHands Code Builder validation ==='
Write-Host '1/3 Running focused backend tests...'
python -m pytest `
  backend/tests/test_openhands_adapter.py `
  backend/tests/test_openhands_workspace_service.py `
  backend/tests/test_openhands_execution_service.py `
  backend/tests/test_openhands_engine.py `
  backend/tests/test_engine_registry.py `
  backend/tests/test_openhands_patch_bridge.py `
  backend/tests/test_openhands_preparation_service.py `
  backend/tests/test_engine_preparation_service.py `
  backend/tests/test_router_engine_bridge.py `
  backend/tests/test_task_engine_integration.py `
  -q

if ($LASTEXITCODE -ne 0) {
  Write-Host 'OPENHANDS CODE BUILDER READY: NO - focused tests failed.'
  exit $LASTEXITCODE
}

Write-Host '2/3 Checking backend...'
try {
  $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/code-builder/health' -TimeoutSec 5
} catch {
  Write-Host 'OPENHANDS CODE BUILDER READY: NO - LUMINA backend is not running on port 8000.'
  Write-Host 'Start LUMINA, then run this same script again.'
  exit 2
}

Write-Host '3/3 Running real OpenHands API preparation task...'
python backend/tests/runtime_validate_openhands_api.py
if ($LASTEXITCODE -ne 0) {
  Write-Host 'OPENHANDS CODE BUILDER READY: NO - real OpenHands API validation failed.'
  exit $LASTEXITCODE
}

Write-Host 'OPENHANDS PREPARATION PATH: PASS'
Write-Host 'NOTE: Apply / backup / rollback validation is the next gate before full READY.'
