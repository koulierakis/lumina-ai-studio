$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host '=== LUMINA Native Code Builder lifecycle validation ==='

Write-Host '1/3 Checking prerequisites (Ollama + qwen2.5-coder:7b)...'
$models = & ollama list 2>$null
if ($LASTEXITCODE -ne 0 -or -not (($models -join ' ') -match 'qwen2\.5-coder:7b')) {
  Write-Host 'NATIVE CODE BUILDER LIFECYCLE: NO - Ollama is not running or qwen2.5-coder:7b is not installed.'
  exit 3
}

Write-Host '2/3 Running the native lifecycle validator (real Ollama planning; typically 6-15 minutes)...'
$gitBefore = @(git status --porcelain)
python backend/tests/runtime_validate_code_builder_native_lifecycle.py @args
$validatorExit = $LASTEXITCODE
$gitAfter = @(git status --porcelain)
if ($validatorExit -ne 0) {
  Write-Host 'NATIVE CODE BUILDER LIFECYCLE: FAIL - see the evidence file under .lumina-runtime/validation/.'
  exit $validatorExit
}
$difference = Compare-Object -ReferenceObject $gitBefore -DifferenceObject $gitAfter
if ($difference) {
  Write-Host 'NATIVE CODE BUILDER LIFECYCLE: FAIL - the git working tree changed during validation:'
  $difference | ForEach-Object { Write-Host $_.InputObject }
  exit 4
}

Write-Host 'NATIVE CODE BUILDER LIFECYCLE: PASS'
Write-Host 'Evidence: .lumina-runtime/validation/native_lifecycle_results_*.json'
