$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host '=== LUMINA OpenHands Code Builder validation ==='
Write-Host '1/5 Running focused backend tests...'
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

Write-Host '2/5 Checking backend...'
try {
  $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/code-builder/health' -TimeoutSec 5
} catch {
  Write-Host 'OPENHANDS CODE BUILDER READY: NO - LUMINA backend is not running on port 8000.'
  Write-Host 'Start LUMINA, then run this same script again.'
  exit 2
}

Write-Host '3/5 Running real scoped OpenHands API preparation task...'
python backend/tests/runtime_validate_openhands_api.py
if ($LASTEXITCODE -ne 0) {
  Write-Host 'OPENHANDS CODE BUILDER READY: NO - real OpenHands API preparation validation failed.'
  exit $LASTEXITCODE
}
Write-Host 'OPENHANDS PREPARATION PATH: PASS'

if ($env:LUMINA_RUN_OPENHANDS_RELIABILITY -eq '1') {
  Write-Host '4/5 Running 10 consecutive real OpenHands preparation tasks...'
  python backend/tests/runtime_validate_openhands_reliability.py
  if ($LASTEXITCODE -ne 0) {
    Write-Host 'OPENHANDS CODE BUILDER READY: NO - 10-task reliability gate failed.'
    exit $LASTEXITCODE
  }
  Write-Host 'OPENHANDS 10-TASK RELIABILITY: PASS'
} else {
  Write-Host '4/5 Ten-task reliability gate not run.'
}

if ($env:LUMINA_RUN_OPENHANDS_APPLY_ROLLBACK -eq '1') {
  Write-Host '5/5 Running controlled approval -> backup -> apply -> rollback validation...'
  python backend/tests/runtime_validate_openhands_apply_rollback.py
  if ($LASTEXITCODE -ne 0) {
    Write-Host 'OPENHANDS CODE BUILDER READY: NO - controlled apply/rollback validation failed.'
    exit $LASTEXITCODE
  }
  Write-Host 'OPENHANDS APPLY / ROLLBACK PATH: PASS'
} else {
  Write-Host '5/5 Apply / rollback gate not run.'
}

if ($env:LUMINA_RUN_OPENHANDS_RELIABILITY -eq '1' -and $env:LUMINA_RUN_OPENHANDS_APPLY_ROLLBACK -eq '1') {
  Write-Host 'OPENHANDS CODE BUILDER RUNTIME GATES: PASS'
  Write-Host 'NEXT GATE: larger real LUMINA change and final UI integration.'
} else {
  Write-Host 'OPENHANDS CODE BUILDER READY: NO - optional runtime gates remain.'
}
