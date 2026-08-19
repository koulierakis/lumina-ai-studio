$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$remoteRef = 'origin/work/code-builder-refresh'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $root ".lumina-runtime\code-builder-remote-update-backups\$stamp"
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$files = @(
    'INSTALL_CODE_BUILDER_REFRESH.ps1',
    'backend/code_builder/router.py',
    'backend/code_builder/task_service.py',
    'backend/code_builder/planning_service.py',
    'frontend/src/pages/CodeBuilder.jsx',
    'frontend/src/pages/CodeBuilder.test.js',
    'backend/tests/test_code_builder_default_build_contract.py',
    'backend/tests/test_code_builder_hardening_contract.py',
    'backend/tests/test_code_builder_idempotency_contract.py',
    'backend/tests/test_code_builder_patch_policy_contract.py',
    'backend/tests/test_code_builder_path_tracking_contract.py',
    'backend/tests/test_code_builder_planning_budget_contract.py',
    'backend/tests/test_code_builder_review_adapter_contract.py',
    'backend/tests/test_code_builder_review_gate_contract.py',
    'backend/tests/test_code_builder_stale_file_contract.py',
    'backend/tests/test_code_builder_timeout_contract.py',
    'tools/apply_code_builder_approval_phase_guard.py',
    'tools/apply_code_builder_hardening.py',
    'tools/apply_code_builder_idempotency_guard.py',
    'tools/apply_code_builder_path_tracking_hardening.py',
    'tools/apply_code_builder_planning_defaults.py',
    'tools/apply_code_builder_policy_hardening.py',
    'tools/apply_code_builder_review_adapter.py',
    'tools/apply_code_builder_review_gate.py',
    'tools/apply_code_builder_stale_guard.py',
    'tools/apply_code_builder_ui_hardening.py'
)

$state = @{}

function Restore-CodeBuilderFiles {
    foreach ($relative in $files) {
        $target = Join-Path $root ($relative -replace '/', '\')
        $entry = $state[$relative]
        if ($null -eq $entry) { continue }
        if ($entry.Existed) {
            Copy-Item $entry.Backup $target -Force
        }
        elseif (Test-Path $target) {
            Remove-Item $target -Force
        }
    }
}

try {
    git fetch origin work/code-builder-refresh
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch the Code Builder branch.' }

    foreach ($relative in $files) {
        $target = Join-Path $root ($relative -replace '/', '\')
        $parent = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $parent | Out-Null

        $safeName = $relative -replace '[\\/:*?"<>|]', '__'
        $backup = Join-Path $backupRoot $safeName
        $existed = Test-Path $target
        if ($existed) {
            Copy-Item $target $backup -Force
        }
        $state[$relative] = [pscustomobject]@{ Existed = $existed; Backup = $backup }

        $content = git show "${remoteRef}:$relative"
        if ($LASTEXITCODE -ne 0) { throw "Could not read $relative from $remoteRef." }
        [System.IO.File]::WriteAllText($target, ($content -join [Environment]::NewLine) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    }

    & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'INSTALL_CODE_BUILDER_REFRESH.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Code Builder finalization checks failed.' }

    Write-Host 'REMOTE CODE BUILDER FINALIZATION COMPLETE' -ForegroundColor Green
}
catch {
    Restore-CodeBuilderFiles
    Write-Host 'REMOTE CODE BUILDER FINALIZATION FAILED - ORIGINAL FILES RESTORED' -ForegroundColor Yellow
    throw
}
