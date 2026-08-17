$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA DRIVE INSTALLER ===' -ForegroundColor Cyan
$branch = 'origin/work/lumina-drive-safety'
$files = @(
  'backend/lumina_drive.py',
  'backend/tests/test_lumina_drive_unit.py',
  'frontend/src/pages/LuminaDrive.jsx',
  'tools/apply_lumina_drive_integration.py'
)

$backup = Join-Path $root '.lumina-runtime\backups\drive-install'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item '.\backend\server.py' (Join-Path $backup 'server.py') -Force
Copy-Item '.\frontend\src\App.js' (Join-Path $backup 'App.js') -Force
Copy-Item '.\frontend\src\platform\moduleRegistry.js' (Join-Path $backup 'moduleRegistry.js') -Force

Write-Host 'Fetching Drive branch...' -ForegroundColor Cyan
git fetch origin | Out-Host
foreach ($file in $files) {
  $dest = Join-Path $root $file
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
  $content = git show "$branch`:$file"
  if ($LASTEXITCODE -ne 0) { throw "Could not read $file from $branch" }
  [System.IO.File]::WriteAllText($dest, ($content -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
  Write-Host "Installed $file" -ForegroundColor Green
}

try {
  python .\tools\apply_lumina_drive_integration.py
  if ($LASTEXITCODE -ne 0) { throw 'Drive integration failed.' }
  python -m py_compile .\backend\lumina_drive.py .\backend\server.py
  if ($LASTEXITCODE -ne 0) { throw 'Drive Python validation failed.' }
  python -m pytest .\backend\tests\test_lumina_drive_unit.py -q
  if ($LASTEXITCODE -ne 0) { throw 'Drive tests failed.' }
  Push-Location .\frontend
  npm run build
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
  Pop-Location
} catch {
  if ((Get-Location).Path -like '*\frontend') { Pop-Location }
  Copy-Item (Join-Path $backup 'server.py') '.\backend\server.py' -Force
  Copy-Item (Join-Path $backup 'App.js') '.\frontend\src\App.js' -Force
  Copy-Item (Join-Path $backup 'moduleRegistry.js') '.\frontend\src\platform\moduleRegistry.js' -Force
  Write-Host 'DRIVE INSTALLATION ROLLED BACK' -ForegroundColor Red
  throw
}

Write-Host ''
Write-Host 'LUMINA DRIVE INSTALLATION COMPLETE' -ForegroundColor Green
Write-Host 'Drive is available at /studio/drive after restart.' -ForegroundColor Green
