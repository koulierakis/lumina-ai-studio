$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA MY VOICE STALE BACKEND FIX ===' -ForegroundColor Cyan

$launcher = Join-Path $root 'launcher\windows\LuminaLauncher.ps1'
if (-not (Test-Path $launcher)) { throw 'LuminaLauncher.ps1 not found.' }

# 1) Harden launcher so a healthy backend on port 8000 is reused only when it belongs
#    to THIS repository. This prevents an older LUMINA checkout from serving the frontend.
$text = [System.IO.File]::ReadAllText($launcher, [System.Text.Encoding]::UTF8)
$old = @'
    # Check if backend is already healthy
    if (Test-BackendHealth) {
        Write-Log "Backend is already healthy at $healthUrl - reusing existing service."
        $owner = Get-PortOwner $BackendPort
        Write-ProcessDetails $owner 'Backend'
        return $true
    }
'@
$new = @'
    # Check if backend is already healthy. Reuse it ONLY when it belongs to this exact repo.
    if (Test-BackendHealth) {
        $owner = Get-PortOwner $BackendPort
        $sameRepo = $false
        if ($owner -and $owner.CommandLine) {
            $sameRepo = $owner.CommandLine -like "*$RepoRoot*"
        }
        if ($sameRepo) {
            Write-Log "Backend is already healthy at $healthUrl and belongs to this repo - reusing existing service."
            Write-ProcessDetails $owner 'Backend'
            return $true
        }
        Write-LogWarn "A healthy backend is running on port $BackendPort, but it does not belong to this repo. It will be replaced."
        Write-ProcessDetails $owner 'Backend'
        if ($owner -and $owner.PID) {
            try { Stop-Process -Id $owner.PID -Force -ErrorAction Stop; Start-Sleep -Seconds 1 } catch { Write-LogWarn "Could not stop stale backend PID $($owner.PID): $_" }
        }
    }
'@
if ($text.Contains($old)) {
    $text = $text.Replace($old, $new)
    [System.IO.File]::WriteAllText($launcher, $text, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Launcher hardened against stale backend reuse.' -ForegroundColor Green
} elseif ($text.Contains('belongs to this repo - reusing existing service')) {
    Write-Host 'Launcher stale-backend protection already installed.' -ForegroundColor DarkGreen
} else {
    Write-Host 'Launcher block differs from expected version; continuing with forced backend restart.' -ForegroundColor Yellow
}

# 2) Force-stop whatever currently owns backend port 8000.
$pids = @()
try {
    $pids = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
} catch {}
if (-not $pids) {
    try {
        $pids = @(netstat -ano | ForEach-Object { if ($_ -match '^\s*TCP\s+\S+:8000\s+\S+\s+LISTENING\s+(\d+)\s*$') { [int]$Matches[1] } } | Where-Object { $_ } | Select-Object -Unique)
    } catch {}
}
foreach ($pidValue in $pids) {
    try {
        $proc = Get-Process -Id $pidValue -ErrorAction Stop
        Write-Host "Stopping backend listener PID $pidValue ($($proc.ProcessName))..." -ForegroundColor Yellow
        Stop-Process -Id $pidValue -Force -ErrorAction Stop
    } catch {}
}
Start-Sleep -Seconds 1

# 3) Start ONLY the backend from this repository. Keep the current frontend/browser alive
#    so the existing in-memory recording is not discarded.
$backendDir = Join-Path $root 'backend'
$logDir = Join-Path $root '.lumina-runtime\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir 'backend.log'
$errLog = Join-Path $logDir 'backend_err.log'

$pythonCandidates = @(
    (Join-Path $root 'backend\.venv\Scripts\python.exe'),
    (Join-Path $root '.venv\Scripts\python.exe'),
    'python.exe',
    'python'
)
$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    try {
        if ($candidate -match '\\' -and -not (Test-Path $candidate)) { continue }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) { $pythonExe = $candidate; break }
    } catch {}
}
if (-not $pythonExe) { throw 'Python 3.11+ not found.' }

Write-Host "Starting exact backend from: $backendDir" -ForegroundColor Cyan
$proc = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','server:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { $ready = $true; break }
    } catch {}
}
if (-not $ready) {
    Write-Host 'Backend failed to become ready. Last backend error lines:' -ForegroundColor Red
    if (Test-Path $errLog) { Get-Content $errLog -Tail 40 }
    throw 'Current LUMINA backend did not become ready.'
}

Write-Host 'CURRENT LUMINA BACKEND READY ON PORT 8000' -ForegroundColor Green
Write-Host 'The browser/frontend was left running. Return to My Voice and press Create My Voice once.' -ForegroundColor Green
