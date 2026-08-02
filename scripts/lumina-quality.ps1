$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

ruff check backend launcher
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
ruff format --check backend launcher
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pytest backend/tests launcher/tests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
try {
  npm run build
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
