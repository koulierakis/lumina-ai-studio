$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA MY VOICE UTF-8 REPAIR ===' -ForegroundColor Cyan

$branch = 'origin/work/personal-voice-complete'
$files = @(
  'backend/voice_providers/elevenlabs_provider.py',
  'backend/voice_providers/__init__.py',
  'frontend/src/pages/PersonalVoiceStudio.jsx',
  'tools/apply_personal_voice_integration.py'
)

Write-Host 'Fetching canonical Personal Voice files...' -ForegroundColor Cyan
git fetch origin | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed.' }

# IMPORTANT: git restore copies blob bytes directly. Do not pipe git show through PowerShell,
# because the console code page can corrupt UTF-8 Greek text before it is written to disk.
git restore --source=$branch --worktree -- $files
if ($LASTEXITCODE -ne 0) { throw 'Could not restore canonical Personal Voice files.' }

Write-Host 'Restored Personal Voice source files byte-for-byte.' -ForegroundColor Green

# Repair the already-inserted backend Personal Voice block as well. The original installer
# may have inserted mojibake into server.py before this fix.
$py = @'
from pathlib import Path
import re

root = Path.cwd()
server_path = root / 'backend' / 'server.py'
patch_path = root / 'tools' / 'apply_personal_voice_integration.py'

server = server_path.read_text(encoding='utf-8')
patch = patch_path.read_text(encoding='utf-8')

m = re.search(r"BACKEND_BLOCK = r'''\n(.*?)\n'''", patch, re.S)
if not m:
    raise RuntimeError('Could not extract canonical BACKEND_BLOCK.')
block = m.group(1)

start = '# ---------- Personal Voice / ElevenLabs integration ----------'
end = '# ---------- Central platform: projects, unified work, search and settings ----------'

if start in server:
    before, rest = server.split(start, 1)
    if end not in rest:
        raise RuntimeError('Could not find backend block end marker.')
    _, after = rest.split(end, 1)
    server = before + block + '\n\n' + end + after
else:
    if end not in server:
        raise RuntimeError('Could not find backend insertion marker.')
    server = server.replace(end, block + '\n\n' + end, 1)

server_path.write_text(server, encoding='utf-8')
print('backend/server.py Personal Voice block repaired as UTF-8')
'@

$py | python -
if ($LASTEXITCODE -ne 0) { throw 'Backend UTF-8 repair failed.' }

Write-Host 'Validating Python...' -ForegroundColor Cyan
python -m py_compile .\backend\server.py .\backend\voice_providers\elevenlabs_provider.py
if ($LASTEXITCODE -ne 0) { throw 'Python validation failed.' }

Write-Host 'Validating Greek UI source...' -ForegroundColor Cyan
$ui = [System.IO.File]::ReadAllText((Join-Path $root 'frontend\src\pages\PersonalVoiceStudio.jsx'), [System.Text.Encoding]::UTF8)
if (-not $ui.Contains('Διάβασε φυσικά')) { throw 'Greek UTF-8 validation failed in PersonalVoiceStudio.jsx.' }

Write-Host ''
Write-Host 'MY VOICE UTF-8 REPAIR COMPLETE' -ForegroundColor Green
Write-Host 'Restart LUMINA and open Voice Studio > My Voice.' -ForegroundColor Green
