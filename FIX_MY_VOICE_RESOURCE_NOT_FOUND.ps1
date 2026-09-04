$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== LUMINA MY VOICE RESOURCE RECOVERY FIX ===' -ForegroundColor Cyan

$path = Join-Path $root 'frontend\src\pages\PersonalVoiceStudio.jsx'
if (-not (Test-Path $path)) { throw 'PersonalVoiceStudio.jsx not found.' }

$src = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)

$old = @'
      const form = new FormData();
      const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('wav') ? 'wav' : 'webm';
      form.append('file', blob, `my-voice.${ext}`);
      await uploadFormData(`/voice/packs/${pack.id}/samples`, form);
      const cloned = await apiPost(`/voice/packs/${pack.id}/clone`, {});
'@

$new = @'
      const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('wav') ? 'wav' : 'webm';
      const uploadSample = async targetPack => {
        const form = new FormData();
        const canonicalBlob = new Blob([blob], { type: ext === 'wav' ? 'audio/wav' : ext === 'ogg' ? 'audio/ogg' : 'audio/webm' });
        form.append('file', canonicalBlob, `my-voice.${ext}`);
        return uploadFormData(`/voice/packs/${targetPack.id}/samples`, form);
      };

      try {
        await uploadSample(pack);
      } catch (uploadError) {
        const message = String(uploadError?.message || '').toLowerCase();
        const stalePack = message.includes('resource not found') || message.includes('voice pack not found') || message.includes('404');
        if (!stalePack) throw uploadError;
        pack = await apiPost('/voice/packs', {
          name: 'My Voice',
          description: 'Personal voice model recorded in LUMINA.',
          language: 'el',
          accent: 'Greek',
          gender: 'male',
          provider: 'elevenlabs',
          consent_confirmed: true,
          ownership_declaration: 'I confirm that this is my own voice and I consent to creating and using this voice model.',
          tags: ['personal-voice', 'greek'],
        });
        await uploadSample(pack);
      }
      const cloned = await apiPost(`/voice/packs/${pack.id}/clone`, {});
'@

if ($src.Contains($new)) {
    Write-Host 'Resource recovery fix already installed.' -ForegroundColor Green
} elseif ($src.Contains($old)) {
    $src = $src.Replace($old, $new)
    [System.IO.File]::WriteAllText($path, $src, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Installed stale Voice Pack recovery and canonical WebM upload.' -ForegroundColor Green
} else {
    throw 'Could not find the My Voice upload block to patch.'
}

Write-Host 'Validating frontend source...' -ForegroundColor Cyan
$check = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
if (-not $check.Contains('const uploadSample = async targetPack')) { throw 'Resource recovery validation failed.' }
if (-not $check.Contains("new Blob([blob], { type:")) { throw 'Canonical audio MIME validation failed.' }

Write-Host ''
Write-Host 'MY VOICE RESOURCE RECOVERY FIX COMPLETE' -ForegroundColor Green
Write-Host 'Restart LUMINA, then press Create My Voice once.' -ForegroundColor Green
