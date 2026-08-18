$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA CODE BUILDER FINALIZATION ===' -ForegroundColor Cyan

$router = Join-Path $root 'backend\code_builder\router.py'
$taskService = Join-Path $root 'backend\code_builder\task_service.py'
$planningService = Join-Path $root 'backend\code_builder\planning_service.py'
$codeBuilderPage = Join-Path $root 'frontend\src\pages\CodeBuilder.jsx'

$tools = @(
    'tools\apply_code_builder_hardening.py',
    'tools\apply_code_builder_path_tracking_hardening.py',
    'tools\apply_code_builder_policy_hardening.py',
    'tools\apply_code_builder_review_gate.py',
    'tools\apply_code_builder_stale_guard.py',
    'tools\apply_code_builder_idempotency_guard.py',
    'tools\apply_code_builder_ui_hardening.py'
)

$backupRoot = Join-Path $root '.lumina-runtime\code-builder-backups'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $backupRoot $stamp
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$filesToProtect = @($router, $taskService, $planningService, $codeBuilderPage)
$backups = @{}
foreach ($file in $filesToProtect) {
    if (-not (Test-Path $file)) { throw "Required Code Builder file is missing: $file" }
    $safeName = ($file.Substring($root.Length).TrimStart('\') -replace '[\\/:*?"<>|]', '__')
    $backup = Join-Path $backupDir $safeName
    Copy-Item $file $backup -Force
    $backups[$file] = $backup
}

try {
    foreach ($toolRelative in $tools) {
        $tool = Join-Path $root $toolRelative
        if (-not (Test-Path $tool)) { throw "Missing Code Builder hardening tool: $toolRelative" }
        Write-Host "Applying $toolRelative..." -ForegroundColor Cyan
        python $tool
        if ($LASTEXITCODE -ne 0) { throw "Code Builder correction failed: $toolRelative" }
    }

    Write-Host 'Checking Code Builder backend files...' -ForegroundColor Cyan
    python -m py_compile .\backend\code_builder\router.py .\backend\code_builder\task_service.py .\backend\code_builder\planning_service.py .\backend\code_builder\patch_service.py .\backend\code_builder\build_service.py
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder compile check failed.' }

    Write-Host 'Running protected Code Builder tests...' -ForegroundColor Cyan
    python -m pytest `
        .\backend\tests\test_code_builder_hardening_contract.py `
        .\backend\tests\test_code_builder_timeout_contract.py `
        .\backend\tests\test_code_builder_default_build_contract.py `
        .\backend\tests\test_code_builder_planning_budget_contract.py `
        .\backend\tests\test_code_builder_patch_policy_contract.py `
        .\backend\tests\test_code_builder_review_gate_contract.py `
        .\backend\tests\test_code_builder_stale_file_contract.py `
        .\backend\tests\test_code_builder_idempotency_contract.py `
        .\backend\tests\test_code_builder_path_tracking_contract.py `
        .\backend\tests\test_code_builder_transaction_boundary.py `
        .\backend\tests\test_code_builder_execution_pipeline.py -q
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder protected tests failed.' }

    Write-Host 'Checking visible Code Builder flow...' -ForegroundColor Cyan
    python -c "from backend.code_builder.router import CodeBuilderTaskPhase; expected={'queued','analyzing','planning','validating','awaiting_approval','approved','applying','verifying','completed'}; actual={x.value for x in CodeBuilderTaskPhase}; missing=expected-actual; assert not missing, f'Missing phases: {missing}'; print('CODE BUILDER FLOW OK')"
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder flow check failed.' }

    Write-Host 'Checking Code Builder UI...' -ForegroundColor Cyan
    Push-Location .\frontend
    try {
        $env:CI = 'true'
        npm test -- --watchAll=false --runInBand src/pages/CodeBuilder.test.js
        if ($LASTEXITCODE -ne 0) { throw 'Code Builder UI test failed.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed.' }
    }
    finally {
        Pop-Location
    }

    $routerText = Get-Content $router -Raw
    if ($routerText -notmatch 'ai_review_unavailable') { throw 'Fail-closed AI review gate is missing.' }
    if ($routerText -notmatch '_lock_prepared_operations_to_validation') { throw 'Stale-file protection is missing.' }
    if ($routerText -notmatch 'idempotency_key_conflict') { throw 'Idempotency conflict protection is missing.' }

    Write-Host ''
    Write-Host 'CODE BUILDER FINALIZATION COMPLETE' -ForegroundColor Green
    Write-Host 'All protected checks passed.' -ForegroundColor Green
    Write-Host 'Only the final real LUMINA runtime smoke test remains.' -ForegroundColor Green
}
catch {
    Write-Host 'A check failed. Restoring all protected Code Builder files...' -ForegroundColor Yellow
    foreach ($file in $filesToProtect) {
        if ($backups.ContainsKey($file) -and (Test-Path $backups[$file])) {
            Copy-Item $backups[$file] $file -Force
        }
    }
    throw
}
