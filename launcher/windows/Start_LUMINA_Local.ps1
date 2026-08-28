$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$launcher = Join-Path $repoRoot 'launcher\lumina_launcher.py'
if (-not (Test-Path $python)) { throw "LUMINA virtual environment not found: $python" }
if (-not (Test-Path $launcher)) { throw "LUMINA launcher not found: $launcher" }
Push-Location $repoRoot
try {
    & $python $launcher start
    if ($LASTEXITCODE -notin 0,2) { throw "LUMINA launcher failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:3000/' -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'LUMINA frontend did not become ready on http://localhost:3000/' }
Start-Process 'http://localhost:3000/studio/documents'
