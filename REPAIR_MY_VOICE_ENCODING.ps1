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

# Copy tracked blobs byte-for-byte so Windows PowerShell cannot reinterpret UTF-8 text.
git restore --source=$branch --worktree -- $files
if ($LASTEXITCODE -ne 0) { throw 'Could not restore canonical Personal Voice files.' }

Write-Host 'Restored Personal Voice source files byte-for-byte.' -ForegroundColor Green

# Repair the already-inserted backend Personal Voice block. The original installer may
# have inserted mojibake into backend/server.py before the byte-safe installer fix.
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

# Validate UTF-8 with Python rather than a Greek literal embedded in Windows PowerShell 5.1.
# This prevents the validator itself from being corrupted by the console/code-page layer.
Write-Host 'Validating UTF-8 source files...' -ForegroundColor Cyan
$validation = @'
from pathlib import Path

files = [
    Path('frontend/src/pages/PersonalVoiceStudio.jsx'),
    Path('tools/apply_personal_voice_integration.py'),
    Path('backend/server.py'),
]
for path in files:
    text = path.read_text(encoding='utf-8', errors='strict')
    if '\ufffd' in text:
        raise RuntimeError(f'Replacement character found in {path}')

ui = Path('frontend/src/pages/PersonalVoiceStudio.jsx').read_text(encoding='utf-8')
required_codepoints = [0x0394, 0x03B9, 0x03AC, 0x03B2, 0x03B1, 0x03C3, 0x03B5]
probe = ''.join(chr(cp) for cp in required_codepoints)
if probe not in ui:
    raise RuntimeError('Expected Greek UTF-8 text was not found in PersonalVoiceStudio.jsx')

print('UTF-8 validation OK')
'@

$validation | python -
if ($LASTEXITCODE -ne 0) { throw 'UTF-8 source validation failed.' }

Write-Host ''
Write-Host 'MY VOICE UTF-8 REPAIR COMPLETE' -ForegroundColor Green
Write-Host 'Restart LUMINA and open Voice Studio > My Voice.' -ForegroundColor Green
