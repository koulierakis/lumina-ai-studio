$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$launcher = Join-Path $repoRoot 'launcher\lumina_launcher.py'
if (-not (Test-Path $python)) { throw "LUMINA virtual environment not found: $python" }
Push-Location $repoRoot
try {
    & $python $launcher stop
    if ($LASTEXITCODE -notin 0,2) { throw "LUMINA stop failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
