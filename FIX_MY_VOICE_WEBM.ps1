$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA MY VOICE WEBM FIX ===' -ForegroundColor Cyan

$server = Join-Path $root 'backend\server.py'
if (-not (Test-Path $server)) { throw 'backend/server.py not found.' }

$py = @'
from pathlib import Path

path = Path('backend/server.py')
text = path.read_text(encoding='utf-8')
old = 'mime = (file.content_type or "").lower()'
new = 'mime = (file.content_type or "").lower().split(";", 1)[0].strip()'
count = text.count(old)
if count == 0:
    if new in text:
        print('WebM MIME normalization already installed.')
    else:
        raise RuntimeError('Could not find the expected audio MIME normalization line.')
else:
    text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')
    print(f'Normalized MIME handling in {count} upload location(s).')
'@

$py | python -
if ($LASTEXITCODE -ne 0) { throw 'MIME patch failed.' }

Write-Host 'Validating backend...' -ForegroundColor Cyan
python -m py_compile .\backend\server.py
if ($LASTEXITCODE -ne 0) { throw 'backend/server.py validation failed.' }

Write-Host ''
Write-Host 'MY VOICE WEBM FIX COMPLETE' -ForegroundColor Green
Write-Host 'Restart LUMINA, keep the same recording if the browser page is still open, and press Create My Voice again.' -ForegroundColor Green
