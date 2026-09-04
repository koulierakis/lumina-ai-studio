$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA CODE BUILDER HARDENING ===' -ForegroundColor Cyan

$router = Join-Path $root 'backend\code_builder\router.py'
$migration = Join-Path $root 'tools\apply_code_builder_phase_contract.py'
$backupDir = Join-Path $root '.lumina-runtime\code-builder-backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$routerBackup = Join-Path $backupDir "router-$stamp.py"
Copy-Item $router $routerBackup -Force
Write-Host "Backup: $routerBackup" -ForegroundColor DarkGray

if (-not (Test-Path $migration)) {
    throw 'Missing tools/apply_code_builder_phase_contract.py'
}

Write-Host 'Applying phase contract and approval hardening...' -ForegroundColor Cyan
python $migration
if ($LASTEXITCODE -ne 0) { throw 'Code Builder migration failed.' }

Write-Host 'Compiling Code Builder backend...' -ForegroundColor Cyan
python -m py_compile .\backend\code_builder\router.py .\backend\code_builder\task_service.py .\backend\code_builder\patch_service.py .\backend\code_builder\planning_service.py
if ($LASTEXITCODE -ne 0) { throw 'Python compilation failed.' }

Write-Host 'Checking runtime phase contract...' -ForegroundColor Cyan
python -c "from backend.code_builder.router import CodeBuilderTaskPhase; expected={'queued','analyzing','planning','validating','awaiting_approval','approved','applying','verifying','completed'}; actual={x.value for x in CodeBuilderTaskPhase}; missing=expected-actual; assert not missing, f'Missing phases: {missing}'; print('PHASE CONTRACT OK')"
if ($LASTEXITCODE -ne 0) { throw 'Phase contract check failed.' }

Write-Host 'Running protected transaction-boundary tests...' -ForegroundColor Cyan
python -m pytest .\backend\tests\test_code_builder_transaction_boundary.py .\backend\tests\test_code_builder_execution_pipeline.py -q
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Tests failed. Restoring router backup...' -ForegroundColor Yellow
    Copy-Item $routerBackup $router -Force
    throw 'Code Builder validation failed; router.py was restored.'
}

Write-Host 'Checking AI BLOCK approval guard...' -ForegroundColor Cyan
$routerText = Get-Content $router -Raw
if ($routerText -notmatch 'ai_review_blocked') {
    Copy-Item $routerBackup $router -Force
    throw 'AI BLOCK approval guard is missing; router.py was restored.'
}

Write-Host ''
Write-Host 'CODE BUILDER HARDENING COMPLETE' -ForegroundColor Green
Write-Host 'Approval remains the write boundary.' -ForegroundColor Green
Write-Host 'Next step later: real runtime smoke test through the LUMINA UI.' -ForegroundColor Green
