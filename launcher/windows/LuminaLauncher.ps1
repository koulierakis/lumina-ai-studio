#Requires -Version 5.1
<#
.SYNOPSIS
  Production-quality Windows desktop launcher for the LUMINA AI Operating System.
.DESCRIPTION
  1. Detects whether Docker Desktop is running.
  2. Starts Docker Desktop if required.
  3. Starts or verifies the required Docker services (Redis and Qdrant).
  4. Starts the LUMINA backend using uvicorn.
  5. Starts the LUMINA frontend using npm start.
  6. Avoids duplicate processes if services are already running.
  7. Waits until backend and frontend health checks confirm readiness.
  8. Opens the LUMINA application in the default browser.
  9. Displays a clear error message if any service fails.
.PARAMETER Action
  "start" (default) or "stop".
.PARAMETER RepoRoot
  Override the auto-detected repository root.
.EXAMPLE
  .\LuminaLauncher.ps1 -Action start
.EXAMPLE
  .\LuminaLauncher.ps1 -Action stop
#>
[CmdletBinding()]
param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'start',

    [string]$RepoRoot,

    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [string]$BackendHost = '127.0.0.1',
    [string]$FrontendHost = 'localhost',

    [int]$StartupTimeoutSeconds = 180,
    [int]$PollIntervalSeconds = 2,

    [string]$DockerComposeFile = 'docker-compose.dev.yml'
)

# ─── Strict mode & error preferences ───────────────────────────
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ─── Derive repository root ────────────────────────────────────
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)

# ─── Paths ─────────────────────────────────────────────────────
$LogDir = Join-Path $RepoRoot '.lumina-runtime\logs'
$LogFile = Join-Path $LogDir 'launcher.log'
$RuntimeDir = Join-Path $RepoRoot '.lumina-runtime'
$ComposeFile = Join-Path $RepoRoot $DockerComposeFile
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'

# ─── Ensure log directory ──────────────────────────────────────
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ─── Logging ───────────────────────────────────────────────────
function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss,fff'
    $line = "$timestamp [$Level] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    if ($Level -eq 'ERROR') {
        Write-Host $line -ForegroundColor Red
    } elseif ($Level -eq 'WARN') {
        Write-Host $line -ForegroundColor Yellow
    } elseif ($Level -eq 'SUCCESS') {
        Write-Host $line -ForegroundColor Green
    } else {
        Write-Host $line -ForegroundColor Cyan
    }
}

function Write-LogError { param([string]$Msg) Write-Log $Msg 'ERROR' }
function Write-LogWarn { param([string]$Msg) Write-Log $Msg 'WARN' }
function Write-LogSuccess { param([string]$Msg) Write-Log $Msg 'SUCCESS' }

# ─── Port check ────────────────────────────────────────────────
function Test-Port {
    param([string]$HostName, [int]$PortNumber)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($HostName, $PortNumber, $null, $null)
        $success = $iar.AsyncWaitHandle.WaitOne(800, $false)
        if ($success) {
            $tcp.EndConnect($iar)
            $tcp.Close()
            return $true
        }
        $tcp.Close()
        return $false
    } catch {
        return $false
    }
}

# ─── HTTP health check ─────────────────────────────────────────
function Test-Http {
    param([string]$Url, [int]$TimeoutMs = 3000)
    try {
        $request = [System.Net.WebRequest]::Create($Url)
        $request.Method = 'GET'
        $request.Timeout = $TimeoutMs
        $response = $request.GetResponse()
        $statusCode = [int]$response.StatusCode
        $response.Close()
        return ($statusCode -ge 200 -and $statusCode -lt 500)
    } catch {
        return $false
    }
}

function Test-BackendHealth {
    param([string]$Host = $BackendHost, [int]$Port = $BackendPort)
    return Test-Http "http://${Host}:${Port}/api/health"
}

function Test-FrontendHealth {
    param([string]$Host = $FrontendHost, [int]$Port = $FrontendPort)
    return Test-Http "http://${Host}:${Port}/"
}

# ─── Wait for readiness ────────────────────────────────────────
function Wait-Ready {
    param(
        [scriptblock]$Probe,
        [string]$Label,
        [int]$TimeoutSec = $StartupTimeoutSeconds,
        [int]$IntervalSec = $PollIntervalSeconds
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $attempts = 0
    while ((Get-Date) -lt $deadline) {
        $attempts++
        if (& $Probe) {
            Write-LogSuccess "$Label is ready (after $attempts attempt(s))."
            return $true
        }
        Start-Sleep -Seconds $IntervalSec
    }
    Write-LogError "$Label readiness timed out after ${TimeoutSec}s ($attempts attempts)."
    return $false
}

# ─── Docker detection ──────────────────────────────────────────
function Get-DockerPath {
    $candidates = @(
        'docker',
        "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin\docker.exe",
        "$env:LOCALAPPDATA\Docker\resources\bin\docker.exe"
    )
    foreach ($c in $candidates) {
        try {
            $proc = Start-Process -FilePath $c -ArgumentList 'version', '--format', '{{.Server.Version}}' `
                -NoNewWindow -PassThru -RedirectStandardOutput "$LogDir\docker_probe.tmp" -RedirectStandardError "$LogDir\docker_probe_err.tmp"
            $proc.WaitForExit(8000) | Out-Null
            if ($proc.ExitCode -eq 0) {
                return $c
            }
        } catch {
            continue
        }
    }
    return $null
}

function Test-DockerRunning {
    param([string]$DockerPath)
    try {
        $proc = Start-Process -FilePath $DockerPath -ArgumentList 'info', '--format', '{{.ServerVersion}}' `
            -NoNewWindow -PassThru -RedirectStandardOutput "$LogDir\docker_info.tmp" -RedirectStandardError "$LogDir\docker_info_err.tmp"
        $proc.WaitForExit(15000) | Out-Null
        return ($proc.ExitCode -eq 0)
    } catch {
        return $false
    }
}

function Start-DockerDesktop {
    $dockerDesktopPaths = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
    )
    foreach ($path in $dockerDesktopPaths) {
        if (Test-Path $path) {
            Write-Log "Starting Docker Desktop: $path"
            Start-Process -FilePath $path
            return $true
        }
    }
    return $false
}

function Wait-DockerReady {
    param([string]$DockerPath, [int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerRunning $DockerPath) {
            Write-LogSuccess 'Docker Desktop is ready.'
            return $true
        }
        Write-Log 'Waiting for Docker Desktop to initialize...'
        Start-Sleep -Seconds 5
    }
    return $false
}

# ─── Docker Compose services ───────────────────────────────────
function Start-DockerServices {
    param([string]$DockerPath)
    if (-not (Test-Path $ComposeFile)) {
        Write-LogWarn "Docker compose file not found: $ComposeFile — skipping Docker services."
        return $true
    }

    Write-Log 'Starting Docker services (Redis, Qdrant)...'
    $args = @('compose', '-f', "`"$ComposeFile`"", 'up', '-d', 'redis', 'qdrant')
    try {
        $proc = Start-Process -FilePath $DockerPath -ArgumentList $args `
            -NoNewWindow -PassThru -Wait -RedirectStandardOutput "$LogDir\docker_compose_up.log" -RedirectStandardError "$LogDir\docker_compose_up_err.log"
        if ($proc.ExitCode -ne 0) {
            Write-LogWarn "docker compose up returned exit code $($proc.ExitCode). Services may already be running."
        }
    } catch {
        Write-LogWarn "docker compose up failed: $_"
    }

    # Verify Redis and Qdrant are up
    $redisReady = Wait-Ready -Probe { Test-Port '127.0.0.1' 6379 } -Label 'Redis' -TimeoutSec 30 -IntervalSec 2
    $qdrantReady = Wait-Ready -Probe { Test-Port '127.0.0.1' 6333 } -Label 'Qdrant' -TimeoutSec 30 -IntervalSec 2

    if (-not $redisReady) {
        Write-LogWarn 'Redis did not become available on port 6379. Backend may still work if it falls back to in-memory mode.'
    }
    if (-not $qdrantReady) {
        Write-LogWarn 'Qdrant did not become available on port 6333. Backend may still work if it falls back to in-memory mode.'
    }
    return $true
}

# ─── Find Python ───────────────────────────────────────────────
function Get-PythonCommand {
    $candidates = @('py -3.12', 'py -3.11', 'py -3', 'python', 'python3')
    foreach ($c in $candidates) {
        try {
            $parts = $c -split ' ', 2
            $exe = $parts[0]
            $verArg = if ($parts.Count -gt 1) { $parts[1] } else { '' }
            $argList = @()
            if ($verArg) { $argList += $verArg }
            $argList += @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)')
            $proc = Start-Process -FilePath $exe -ArgumentList $argList -NoNewWindow -PassThru -RedirectStandardOutput "$LogDir\py_probe.tmp" -RedirectStandardError "$LogDir\py_probe_err.tmp"
            $proc.WaitForExit(8000) | Out-Null
            if ($proc.ExitCode -eq 0) {
                return $c
            }
        } catch {
            continue
        }
    }
    return $null
}

# ─── Find npm ──────────────────────────────────────────────────
function Get-NpmPath {
    $candidates = @('npm.cmd', 'npm')
    foreach ($c in $candidates) {
        try {
            $proc = Start-Process -FilePath $c -ArgumentList '--version' -NoNewWindow -PassThru -RedirectStandardOutput "$LogDir\npm_probe.tmp" -RedirectStandardError "$LogDir\npm_probe_err.tmp"
            $proc.WaitForExit(8000) | Out-Null
            if ($proc.ExitCode -eq 0) {
                return $c
            }
        } catch {
            continue
        }
    }
    return $null
}

# ─── Start backend ─────────────────────────────────────────────
function Start-Backend {
    if (Test-BackendHealth) {
        Write-Log 'Backend is already responding on port $BackendPort — skipping start.'
        return $true
    }
    if (Test-Port $BackendHost $BackendPort) {
        Write-LogError "Port $BackendPort is occupied but backend health check failed."
        return $false
    }

    $pythonCmd = Get-PythonCommand
    if (-not $pythonCmd) {
        Write-LogError 'Python 3.11+ not found on PATH.'
        return $false
    }

    $parts = $pythonCmd -split ' ', 2
    $pyExe = $parts[0]
    $pyVerArg = if ($parts.Count -gt 1) { @($parts[1]) } else { @() }

    $args = $pyVerArg + @('-m', 'uvicorn', 'server:app', '--host', $BackendHost, '--port', $BackendPort)
    Write-Log "Starting backend: $pyExe $($args -join ' ')"

    $env = @{
        'PYTHONUNBUFFERED' = '1'
    }

    try {
        $proc = Start-Process -FilePath $pyExe -ArgumentList $args `
            -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput "$LogDir\backend.log" -RedirectStandardError "$LogDir\backend_err.log"
        Write-Log "Backend process started (PID: $($proc.Id))."
    } catch {
        Write-LogError "Failed to start backend: $_"
        return $false
    }

    $ready = Wait-Ready -Probe { Test-BackendHealth } -Label 'Backend' -TimeoutSec $StartupTimeoutSeconds
    return $ready
}

# ─── Start frontend ────────────────────────────────────────────
function Start-Frontend {
    if (Test-FrontendHealth) {
        Write-Log "Frontend is already responding on port $FrontendPort — skipping start."
        return $true
    }
    if (Test-Port '127.0.0.1' $FrontendPort) {
        Write-LogError "Port $FrontendPort is occupied but frontend health check failed."
        return $false
    }

    $npmPath = Get-NpmPath
    if (-not $npmPath) {
        Write-LogError 'npm not found on PATH.'
        return $false
    }

    Write-Log "Starting frontend: $npmPath start"

    try {
        $proc = Start-Process -FilePath $npmPath -ArgumentList 'start' `
            -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput "$LogDir\frontend.log" -RedirectStandardError "$LogDir\frontend_err.log"
        Write-Log "Frontend process started (PID: $($proc.Id))."
    } catch {
        Write-LogError "Failed to start frontend: $_"
        return $false
    }

    $ready = Wait-Ready -Probe { Test-FrontendHealth } -Label 'Frontend' -TimeoutSec $StartupTimeoutSeconds
    return $ready
}

# ─── Open browser ──────────────────────────────────────────────
function Open-Browser {
    $url = "http://${FrontendHost}:${FrontendPort}/"
    Write-Log "Opening browser: $url"
    try {
        Start-Process $url
        Write-LogSuccess 'Browser opened.'
    } catch {
        Write-LogWarn "Could not open browser: $_"
    }
}

# ─── Stop LUMINA processes ─────────────────────────────────────
function Stop-Lumina {
    Write-Log 'Stopping LUMINA-owned processes...'

    # Stop frontend (node processes on port 3000)
    $frontendPids = Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -ErrorAction SilentlyContinue
    if ($frontendPids) {
        foreach ($pid in $frontendPids) {
            try {
                $proc = Get-Process -Id $pid -ErrorAction Stop
                if ($proc.ProcessName -match 'node') {
                    Write-Log "Stopping frontend process (PID: $pid, $($proc.ProcessName))"
                    Stop-Process -Id $pid -Force -ErrorAction Stop
                }
            } catch {
                # Process may have already exited
            }
        }
    }

    # Stop backend (python processes on port 8000)
    $backendPids = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -ErrorAction SilentlyContinue
    if ($backendPids) {
        foreach ($pid in $backendPids) {
            try {
                $proc = Get-Process -Id $pid -ErrorAction Stop
                if ($proc.ProcessName -match 'python') {
                    Write-Log "Stopping backend process (PID: $pid, $($proc.ProcessName))"
                    Stop-Process -Id $pid -Force -ErrorAction Stop
                }
            } catch {
                # Process may have already exited
            }
        }
    }

    Write-LogSuccess 'LUMINA processes stopped. Docker Desktop and containers remain running.'
}

# ─── Status report ─────────────────────────────────────────────
function Show-Status {
    Write-Log '=== LUMINA Status ==='
    $backendOk = Test-BackendHealth
    $frontendOk = Test-FrontendHealth
    $redisOk = Test-Port '127.0.0.1' 6379
    $qdrantOk = Test-Port '127.0.0.1' 6333

    Write-Log ("Backend  (port $BackendPort): {0}" -f $(if ($backendOk) { 'RUNNING' } else { 'STOPPED' }))
    Write-Log ("Frontend (port $FrontendPort): {0}" -f $(if ($frontendOk) { 'RUNNING' } else { 'STOPPED' }))
    Write-Log ("Redis    (port 6379): {0}" -f $(if ($redisOk) { 'RUNNING' } else { 'STOPPED' }))
    Write-Log ("Qdrant   (port 6333): {0}" -f $(if ($qdrantOk) { 'RUNNING' } else { 'STOPPED' }))
}

# ─── Main: START ───────────────────────────────────────────────
function Invoke-Start {
    Write-Log '========================================'
    Write-Log 'LUMINA AI — Starting...'
    Write-Log "Repository: $RepoRoot"
    Write-Log '========================================'

    # Check if already running
    $backendRunning = Test-BackendHealth
    $frontendRunning = Test-FrontendHealth

    if ($backendRunning -and $frontendRunning) {
        Write-Log 'LUMINA is already running. Opening browser...'
        Open-Browser
        return 0
    }

    # 1. Docker Desktop detection
    Write-Log 'Step 1: Checking Docker Desktop...'
    $dockerPath = Get-DockerPath
    if ($dockerPath) {
        Write-Log "Docker found: $dockerPath"
        if (-not (Test-DockerRunning $dockerPath)) {
            Write-Log 'Docker Desktop is not running. Attempting to start it...'
            $started = Start-DockerDesktop
            if ($started) {
                $dockerReady = Wait-DockerReady $dockerPath -TimeoutSec 120
                if (-not $dockerReady) {
                    Write-LogError 'Docker Desktop did not become ready within 120 seconds.'
                    Write-LogError 'LUMINA can still start without Docker, but Redis and Qdrant will be unavailable.'
                }
            } else {
                Write-LogWarn 'Docker Desktop executable not found. Continuing without Docker services.'
            }
        } else {
            Write-LogSuccess 'Docker Desktop is already running.'
        }

        # 2. Start Docker services
        if (Test-DockerRunning $dockerPath) {
            Write-Log 'Step 2: Starting Docker services (Redis, Qdrant)...'
            Start-DockerServices $dockerPath | Out-Null
        }
    } else {
        Write-LogWarn 'Docker not found on PATH. Redis and Qdrant will be unavailable.'
        Write-LogWarn 'LUMINA backend may still start in degraded mode.'
    }

    # 3. Start backend
    Write-Log 'Step 3: Starting backend...'
    $backendOk = Start-Backend
    if (-not $backendOk) {
        Write-LogError 'Backend failed to start. Aborting.'
        return 1
    }

    # 4. Start frontend
    Write-Log 'Step 4: Starting frontend...'
    $frontendOk = Start-Frontend
    if (-not $frontendOk) {
        Write-LogError 'Frontend failed to start. Aborting.'
        return 1
    }

    # 5. Open browser
    Write-Log 'Step 5: Opening browser...'
    Open-Browser

    Write-LogSuccess '========================================'
    Write-LogSuccess 'LUMINA AI is ready!'
    Write-LogSuccess '========================================'
    return 0
}

# ─── Main: STOP ────────────────────────────────────────────────
function Invoke-Stop {
    Write-Log '========================================'
    Write-Log 'LUMINA AI — Stopping...'
    Write-Log '========================================'
    Stop-Lumina
    return 0
}

# ─── Entry point ───────────────────────────────────────────────
try {
    switch ($Action) {
        'start' { $exitCode = Invoke-Start }
        'stop' { $exitCode = Invoke-Stop }
        'status' { Show-Status; $exitCode = 0 }
    }
} catch {
    Write-LogError "Unexpected error: $_"
    Write-LogError $_.ScriptStackTrace
    $exitCode = 1
}

exit $exitCode