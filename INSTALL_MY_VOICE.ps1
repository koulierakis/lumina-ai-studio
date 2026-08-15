$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA MY VOICE INSTALLER ===' -ForegroundColor Cyan

$branch = 'origin/work/personal-voice-complete'
$files = @(
  'backend/voice_providers/elevenlabs_provider.py',
  'backend/voice_providers/__init__.py',
  'frontend/src/pages/PersonalVoiceStudio.jsx',
  'tools/apply_personal_voice_integration.py'
)

Write-Host 'Fetching latest Personal Voice branch...' -ForegroundColor Cyan
git fetch origin | Out-Host

foreach ($file in $files) {
  $dest = Join-Path $root $file
  $dir = Split-Path -Parent $dest
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $content = git show "$branch`:$file"
  if ($LASTEXITCODE -ne 0) { throw "Could not read $file from $branch" }
  [System.IO.File]::WriteAllText($dest, ($content -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
  Write-Host "Installed $file" -ForegroundColor Green
}

Write-Host 'Applying backend and Voice Studio integration...' -ForegroundColor Cyan
python .\tools\apply_personal_voice_integration.py
if ($LASTEXITCODE -ne 0) { throw 'Personal Voice integration patch failed.' }

Write-Host 'Validating Python...' -ForegroundColor Cyan
python -m py_compile .\backend\server.py .\backend\voice_providers\elevenlabs_provider.py
if ($LASTEXITCODE -ne 0) { throw 'Python validation failed.' }

Write-Host 'Validating frontend import...' -ForegroundColor Cyan
if (-not (Select-String -Path .\frontend\src\pages\VoiceStudio.jsx -Pattern "PersonalVoiceStudio" -Quiet)) {
  throw 'VoiceStudio.jsx was not connected to PersonalVoiceStudio.'
}

Write-Host ''
Write-Host 'MY VOICE INSTALLATION COMPLETE' -ForegroundColor Green
Write-Host 'Next: restart LUMINA and open Voice Studio > My Voice.' -ForegroundColor Green
