$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$launcher = Join-Path $repoRoot 'launcher\lumina_launcher.py'
if (-not (Test-Path $python)) { throw "LUMINA virtual environment not found: $python" }
if (-not (Test-Path $launcher)) { throw "LUMINA launcher not found: $launcher" }

# Force deterministic local routing. This prevents stale machine-level environment
# variables from sending the browser back to an old Codespace/Emergent backend.
$env:REACT_APP_BACKEND_URL = 'http://127.0.0.1:8000'
$env:LUMINA_LOCAL_PASSWORDLESS = '1'

Push-Location $repoRoot
try {
    & $python $launcher start
    if ($LASTEXITCODE -notin 0,2) { throw "LUMINA launcher failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$backendReady = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2
        if ($health.StatusCode -eq 200) { $backendReady = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $backendReady) { throw 'LUMINA backend did not become ready on http://127.0.0.1:8000/api/health' }

$documentApiReady = $false
try {
    $templates = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/documents/templates' -UseBasicParsing -TimeoutSec 5
    $profile = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/documents/company-profile' -UseBasicParsing -TimeoutSec 5
    $documents = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/documents' -UseBasicParsing -TimeoutSec 5
    $documentApiReady = ($templates.StatusCode -eq 200 -and $profile.StatusCode -eq 200 -and $documents.StatusCode -eq 200)
} catch {}
if (-not $documentApiReady) { throw 'LUMINA Document Studio backend API is not responding correctly.' }

$frontendReady = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:3000/' -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $frontendReady = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $frontendReady) { throw 'LUMINA frontend did not become ready on http://localhost:3000/' }

Start-Process 'http://localhost:3000/'
