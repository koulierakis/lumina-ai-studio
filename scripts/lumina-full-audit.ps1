# Run from anywhere: powershell -File scripts/lumina-full-audit.ps1
# Continue through failures and print one summary; do not close an interactive shell.
$root = Split-Path -Parent $PSScriptRoot
$results = [ordered]@{}
$python = if (Test-Path (Join-Path $root '.venv/Scripts/python.exe')) {
    Join-Path $root '.venv/Scripts/python.exe'
} elseif (Test-Path (Join-Path $root '.venv/bin/python')) {
    Join-Path $root '.venv/bin/python'
} else { 'python' }

function Invoke-AuditStep {
    param([string]$Name, [string]$Directory, [string]$Executable, [string[]]$Arguments)
    Write-Host "`n=== $Name ==="
    Push-Location $Directory
    try {
        & $Executable @Arguments
        $results[$Name] = if ($LASTEXITCODE -eq 0) { 'PASS' } else { "FAIL ($LASTEXITCODE)" }
    } catch {
        $results[$Name] = "FAIL ($($_.Exception.Message))"
    } finally { Pop-Location }
}

Invoke-AuditStep 'Backend tests' $root $python @('-m', 'pytest', 'backend/tests', 'launcher/tests', '-q')
Invoke-AuditStep 'Backend startup and authentication' $root $python @('scripts/lumina-smoke.py')
Invoke-AuditStep 'Frontend tests' (Join-Path $root 'frontend') 'npm' @('test', '--', '--watchAll=false', '--runInBand')
Invoke-AuditStep 'Frontend build' (Join-Path $root 'frontend') 'npm' @('run', 'build')
Invoke-AuditStep 'Dependency audit' (Join-Path $root 'frontend') 'npm' @('audit', '--audit-level=high')
if (Get-Command ruff -ErrorAction SilentlyContinue) {
    Invoke-AuditStep 'Python static analysis' $root 'ruff' @('check', 'backend', 'launcher')
} else {
    $results['Python static analysis'] = 'UNAVAILABLE (ruff not installed)'
}
$gitStatus = & git -C $root status --porcelain
$gitBranch = & git -C $root branch --show-current
$results['Git state'] = if ($LASTEXITCODE -eq 0 -and $gitBranch -eq 'work/lumina-production-unified' -and -not $gitStatus) {
    'PASS (expected branch, clean)'
} else { "REVIEW (branch: $gitBranch; changed entries: $(@($gitStatus).Count))" }
Write-Host "`n=== LUMINA AUDIT SUMMARY ==="
foreach ($item in $results.GetEnumerator()) { Write-Host ("{0}: {1}" -f $item.Key, $item.Value) }
Write-Host 'SonarCloud and production deployment require their connected services; inspect their own checks separately.'
