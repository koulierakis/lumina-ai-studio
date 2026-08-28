$ErrorActionPreference = 'Stop'

$repoUrl = 'https://github.com/koulierakis/lumina-ai-studio.git'
$branch = 'install/local-windows-lumina-v2'
$desktop = [Environment]::GetFolderPath('Desktop')
$target = Join-Path $desktop 'LUMINA_LOCAL'
$log = Join-Path $desktop 'LUMINA_LOCAL_INSTALL.log'

function Write-Status([string]$Text) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Text"
    Write-Host $line
    Add-Content -Path $log -Value $line
}

try {
    Set-Content -Path $log -Value "LUMINA local installer started $(Get-Date)"
    Write-Status 'Checking required tools...'

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is not installed or not on PATH.' }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is not installed or not on PATH.' }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'npm is not installed or not on PATH.' }

    $python = $null
    foreach ($candidate in @('py','python')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            try {
                if ($candidate -eq 'py') {
                    & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
                    if ($LASTEXITCODE -eq 0) { $python = @('py','-3.11'); break }
                    & py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
                    if ($LASTEXITCODE -eq 0) { $python = @('py','-3.12'); break }
                } else {
                    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
                    if ($LASTEXITCODE -eq 0) { $python = @('python'); break }
                }
            } catch {}
        }
    }
    if (-not $python) { throw 'Python 3.11 or newer was not found.' }

    if (Test-Path $target) {
        Write-Status "Existing LUMINA_LOCAL found. Updating safely..."
        Push-Location $target
        git fetch origin $branch
        if ($LASTEXITCODE -ne 0) { throw 'git fetch failed.' }
        git checkout $branch
        if ($LASTEXITCODE -ne 0) { throw 'git checkout failed.' }
        git pull --ff-only origin $branch
        if ($LASTEXITCODE -ne 0) { throw 'git pull failed. Local changes may need review.' }
        Pop-Location
    } else {
        Write-Status "Cloning LUMINA to $target ..."
        git clone --branch $branch --single-branch $repoUrl $target
        if ($LASTEXITCODE -ne 0) { throw 'git clone failed.' }
    }

    Write-Status 'Installing frontend dependencies...'
    Push-Location (Join-Path $target 'frontend')
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    Pop-Location

    $venv = Join-Path $target '.venv'
    if (-not (Test-Path $venv)) {
        Write-Status 'Creating Python virtual environment...'
        if ($python.Count -eq 2) { & $python[0] $python[1] -m venv $venv } else { & $python[0] -m venv $venv }
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }

    $venvPython = Join-Path $venv 'Scripts\python.exe'
    Write-Status 'Installing backend dependencies...'
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $target 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }

    Write-Status 'Creating desktop shortcuts...'
    $shell = New-Object -ComObject WScript.Shell
    $startScript = Join-Path $target 'launcher\windows\Start_LUMINA.vbs'
    $stopScript = Join-Path $target 'launcher\windows\Stop_LUMINA.vbs'

    $startShortcut = $shell.CreateShortcut((Join-Path $desktop 'LUMINA AI Studio.lnk'))
    $startShortcut.TargetPath = 'wscript.exe'
    $startShortcut.Arguments = '"' + $startScript + '"'
    $startShortcut.WorkingDirectory = $target
    $icon = Join-Path $target 'frontend\public\favicon.ico'
    if (Test-Path $icon) { $startShortcut.IconLocation = $icon }
    $startShortcut.Description = 'Start LUMINA AI Studio locally'
    $startShortcut.Save()

    $stopShortcut = $shell.CreateShortcut((Join-Path $desktop 'Close LUMINA.lnk'))
    $stopShortcut.TargetPath = 'wscript.exe'
    $stopShortcut.Arguments = '"' + $stopScript + '"'
    $stopShortcut.WorkingDirectory = $target
    $stopShortcut.Description = 'Stop LUMINA AI Studio local services'
    $stopShortcut.Save()

    $urlFile = Join-Path $desktop 'LUMINA Document Studio.url'
    Set-Content -Path $urlFile -Value "[InternetShortcut]`r`nURL=http://localhost:3000/studio/documents`r`n"

    Write-Status 'Running LUMINA doctor...'
    Push-Location $target
    & $venvPython launcher\lumina_launcher.py doctor | Tee-Object -FilePath $log -Append
    Pop-Location

    Write-Status 'Starting LUMINA locally...'
    Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + $startScript + '"') -WorkingDirectory $target

    Write-Status 'Waiting for frontend...'
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        try {
            $response = Invoke-WebRequest -Uri 'http://localhost:3000/' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "LUMINA did not become ready on http://localhost:3000/. Check $target\.lumina-runtime\logs and $log" }

    Write-Status 'LUMINA is ready.'
    Start-Process 'http://localhost:3000/studio/documents'
    [System.Windows.Forms.MessageBox]::Show('LUMINA AI Studio installed successfully.\n\nDesktop shortcut: LUMINA AI Studio\nDocument Studio: http://localhost:3000/studio/documents', 'LUMINA') | Out-Null
}
catch {
    Add-Type -AssemblyName System.Windows.Forms
    $msg = $_.Exception.Message + "`n`nInstall log:`n" + $log
    Write-Status ('ERROR: ' + $_.Exception.Message)
    [System.Windows.Forms.MessageBox]::Show($msg, 'LUMINA Installation Error') | Out-Null
    exit 1
}
