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
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed.' }

# Copy Git blobs byte-for-byte. Avoid piping `git show` through PowerShell because
# the active Windows console code page can corrupt UTF-8 Greek text.
git restore --source=$branch --worktree -- $files
if ($LASTEXITCODE -ne 0) { throw 'Could not restore Personal Voice files from branch.' }

foreach ($file in $files) {
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

$ui = [System.IO.File]::ReadAllText((Join-Path $root 'frontend\src\pages\PersonalVoiceStudio.jsx'), [System.Text.Encoding]::UTF8)
if (-not $ui.Contains('Διάβασε φυσικά')) { throw 'Greek UTF-8 validation failed in PersonalVoiceStudio.jsx.' }

Write-Host ''
Write-Host 'MY VOICE INSTALLATION COMPLETE' -ForegroundColor Green
Write-Host 'Next: restart LUMINA and open Voice Studio > My Voice.' -ForegroundColor Green
