$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root 'launcher\windows\LuminaLauncher.ps1'
if (-not (Test-Path $launcher)) { throw "LuminaLauncher.ps1 not found: $launcher" }

$content = [System.IO.File]::ReadAllText($launcher, [System.Text.UTF8Encoding]::new($false))
$marker = '# LUMINA_ELEVENLABS_USER_ENV_HYDRATION'

if ($content -notmatch [regex]::Escape($marker)) {
    $anchor = '$ErrorActionPreference = ''Stop'''
    if (-not $content.Contains($anchor)) { throw 'Could not find launcher insertion anchor.' }

    $block = @'

# LUMINA_ELEVENLABS_USER_ENV_HYDRATION
# A launcher started from Explorer/WScript may inherit an older process environment
# even after a persistent User-scope variable was created. Hydrate the credential
# explicitly from the User environment store into this launcher process before
# starting uvicorn, so the backend always receives ELEVENLABS_API_KEY.
$elevenLabsUserKey = [Environment]::GetEnvironmentVariable('ELEVENLABS_API_KEY', 'User')
if (-not [string]::IsNullOrWhiteSpace($elevenLabsUserKey)) {
    [Environment]::SetEnvironmentVariable('ELEVENLABS_API_KEY', $elevenLabsUserKey, 'Process')
    $env:ELEVENLABS_API_KEY = $elevenLabsUserKey
}
Remove-Variable elevenLabsUserKey -ErrorAction SilentlyContinue
'@

    $content = $content.Replace($anchor, $anchor + $block)
    [System.IO.File]::WriteAllText($launcher, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host 'Launcher patched to hydrate ELEVENLABS_API_KEY from User scope.' -ForegroundColor Green
} else {
    Write-Host 'Launcher already contains ElevenLabs User-scope hydration.' -ForegroundColor Yellow
}

$userKey = [Environment]::GetEnvironmentVariable('ELEVENLABS_API_KEY', 'User')
if ([string]::IsNullOrWhiteSpace($userKey)) {
    throw 'ELEVENLABS_API_KEY is not present in Windows User environment. Re-save the key before launching LUMINA.'
}
Write-Host ('Persistent User key detected: YES (length ' + $userKey.Length + ')') -ForegroundColor Green
Remove-Variable userKey -ErrorAction SilentlyContinue

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launcher -Action stop -RepoRoot $root
Start-Sleep -Seconds 2
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launcher -Action start -RepoRoot $root
if ($LASTEXITCODE -ne 0) { throw "LUMINA launcher failed with exit code $LASTEXITCODE" }

Write-Host ''
Write-Host 'ELEVENLABS ENVIRONMENT INHERITANCE FIX COMPLETE' -ForegroundColor Green
Write-Host 'LUMINA restarted with the persistent ElevenLabs API key loaded into the backend process.' -ForegroundColor Green
