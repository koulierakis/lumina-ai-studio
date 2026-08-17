$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA MENTOR INSTALLER ===' -ForegroundColor Cyan
$branch = 'origin/work/mentor-complete'
$files = @(
  'backend/mentor.py',
  'backend/tests/test_mentor_unit.py',
  'frontend/src/pages/Mentor.jsx',
  'tools/apply_mentor_integration.py'
)

$backup = Join-Path $root '.lumina-runtime\backups\mentor-install'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item '.\backend\server.py' (Join-Path $backup 'server.py') -Force
Copy-Item '.\frontend\src\App.js' (Join-Path $backup 'App.js') -Force
Copy-Item '.\frontend\src\platform\moduleRegistry.js' (Join-Path $backup 'moduleRegistry.js') -Force

Write-Host 'Fetching Mentor branch...' -ForegroundColor Cyan
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
  python .\tools\apply_mentor_integration.py
  if ($LASTEXITCODE -ne 0) { throw 'Mentor integration failed.' }
  python -m py_compile .\backend\mentor.py .\backend\server.py
  if ($LASTEXITCODE -ne 0) { throw 'Mentor Python validation failed.' }
  python -m pytest .\backend\tests\test_mentor_unit.py -q
  if ($LASTEXITCODE -ne 0) { throw 'Mentor unit tests failed.' }
  Push-Location .\frontend
  npm run build
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
  Pop-Location
} catch {
  if ((Get-Location).Path -like '*\frontend') { Pop-Location }
  Copy-Item (Join-Path $backup 'server.py') '.\backend\server.py' -Force
  Copy-Item (Join-Path $backup 'App.js') '.\frontend\src\App.js' -Force
  Copy-Item (Join-Path $backup 'moduleRegistry.js') '.\frontend\src\platform\moduleRegistry.js' -Force
  Write-Host 'MENTOR INSTALLATION ROLLED BACK' -ForegroundColor Red
  throw
}

Write-Host ''
Write-Host 'MENTOR INSTALLATION COMPLETE' -ForegroundColor Green
Write-Host 'Mentor is available at /studio/mentor after LUMINA restart.' -ForegroundColor Green
