$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA CODE BUILDER FINALIZATION ===' -ForegroundColor Cyan

$router = Join-Path $root 'backend\code_builder\router.py'
$hardening = Join-Path $root 'tools\apply_code_builder_hardening.py'
$backupDir = Join-Path $root '.lumina-runtime\code-builder-backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$routerBackup = Join-Path $backupDir "router-$stamp.py"
Copy-Item $router $routerBackup -Force

try {
    if (-not (Test-Path $hardening)) { throw 'Missing Code Builder hardening tool.' }

    Write-Host 'Applying Code Builder corrections...' -ForegroundColor Cyan
    python $hardening
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder correction failed.' }

    Write-Host 'Checking Code Builder files...' -ForegroundColor Cyan
    python -m py_compile .\backend\code_builder\router.py .\backend\code_builder\task_service.py .\backend\code_builder\planning_service.py .\backend\code_builder\patch_service.py .\backend\code_builder\build_service.py
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder compile check failed.' }

    Write-Host 'Checking protected workflow...' -ForegroundColor Cyan
    python -m pytest .\backend\tests\test_code_builder_hardening_contract.py .\backend\tests\test_code_builder_transaction_boundary.py .\backend\tests\test_code_builder_execution_pipeline.py -q
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder protected tests failed.' }

    python -c "from backend.code_builder.router import CodeBuilderTaskPhase; expected={'queued','analyzing','planning','validating','awaiting_approval','approved','applying','verifying','completed'}; actual={x.value for x in CodeBuilderTaskPhase}; missing=expected-actual; assert not missing, f'Missing phases: {missing}'; print('CODE BUILDER FLOW OK')"
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder flow check failed.' }

    $routerText = Get-Content $router -Raw
    if ($routerText -notmatch 'ai_review_blocked') { throw 'Safety approval guard is missing.' }

    Write-Host ''
    Write-Host 'CODE BUILDER FINALIZATION COMPLETE' -ForegroundColor Green
    Write-Host 'The protected approval workflow is installed and verified.' -ForegroundColor Green
    Write-Host 'Only the final real LUMINA runtime test remains.' -ForegroundColor Green
}
catch {
    Write-Host 'A check failed. Restoring the previous Code Builder file...' -ForegroundColor Yellow
    Copy-Item $routerBackup $router -Force
    throw
}
