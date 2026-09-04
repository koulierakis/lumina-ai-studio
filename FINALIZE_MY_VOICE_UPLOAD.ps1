$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA MY VOICE FINAL UPLOAD FIX ===' -ForegroundColor Cyan

$py = @'
from pathlib import Path

root = Path.cwd()
server_path = root / 'backend' / 'server.py'
ui_path = root / 'frontend' / 'src' / 'pages' / 'PersonalVoiceStudio.jsx'

server = server_path.read_text(encoding='utf-8')
ui = ui_path.read_text(encoding='utf-8')

old_backend = '''    mime = (file.content_type or "").lower().split(";", 1)[0].strip()
    if mime not in ALLOWED_AUDIO_MIMES: raise HTTPException(400, "Upload WAV, MP3, OGG, or WebM audio samples only.")'''
new_backend = '''    raw_mime = (file.content_type or "").lower().strip()
    mime = raw_mime.split(";", 1)[0].strip()
    filename_lower = (file.filename or "").lower()
    if mime in {"", "application/octet-stream", "binary/octet-stream"}:
        if filename_lower.endswith(".webm"):
            mime = "audio/webm"
        elif filename_lower.endswith(".ogg") or filename_lower.endswith(".oga"):
            mime = "audio/ogg"
        elif filename_lower.endswith(".wav"):
            mime = "audio/wav"
        elif filename_lower.endswith(".mp3"):
            mime = "audio/mpeg"
    if mime not in ALLOWED_AUDIO_MIMES:
        raise HTTPException(400, f"Unsupported voice sample type: {raw_mime or 'unknown'} ({file.filename or 'unnamed'}). Upload WAV, MP3, OGG, or WebM audio samples only.")'''

if old_backend in server:
    server = server.replace(old_backend, new_backend, 1)
elif 'raw_mime = (file.content_type or "").lower().strip()' not in server:
    raise RuntimeError('Could not locate My Voice sample MIME validation block in backend/server.py')

old_ui = "      form.append('file', blob, `my-voice.${ext}`);"
new_ui = "      const uploadMime = ext === 'ogg' ? 'audio/ogg' : ext === 'wav' ? 'audio/wav' : 'audio/webm';\n      const uploadFile = new File([blob], `my-voice.${ext}`, { type: uploadMime });\n      form.append('file', uploadFile);"
if old_ui in ui:
    ui = ui.replace(old_ui, new_ui, 1)
elif 'const uploadFile = new File([blob]' not in ui:
    raise RuntimeError('Could not locate My Voice FormData upload line in PersonalVoiceStudio.jsx')

server_path.write_text(server, encoding='utf-8')
ui_path.write_text(ui, encoding='utf-8')
print('Backend MIME fallback hardened')
print('Frontend upload MIME normalized')
'@

$py | python -
if ($LASTEXITCODE -ne 0) { throw 'My Voice final upload patch failed.' }

Write-Host 'Validating backend...' -ForegroundColor Cyan
python -m py_compile .\backend\server.py
if ($LASTEXITCODE -ne 0) { throw 'Backend validation failed.' }

Write-Host 'Validating frontend patch...' -ForegroundColor Cyan
$check = @'
from pathlib import Path
text = Path('frontend/src/pages/PersonalVoiceStudio.jsx').read_text(encoding='utf-8')
assert "new File([blob]" in text
assert "uploadMime" in text
print('Frontend validation OK')
'@
$check | python -
if ($LASTEXITCODE -ne 0) { throw 'Frontend validation failed.' }

Write-Host ''
Write-Host 'MY VOICE FINAL UPLOAD FIX COMPLETE' -ForegroundColor Green
Write-Host 'The upload path now accepts Chrome WebM/Opus robustly and sends a canonical audio/webm MIME type.' -ForegroundColor Green
