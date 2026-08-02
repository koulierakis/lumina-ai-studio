$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$base = if ($env:LUMINA_DIFF_BASE) { $env:LUMINA_DIFF_BASE } else { "HEAD" }
$files = @(git diff --name-only --diff-filter=ACMR $base -- "*.py")
$files += @(git ls-files --others --exclude-standard -- "*.py")
$files = @($files | Sort-Object -Unique | Where-Object { Test-Path $_ })

if ($files.Count -eq 0) {
  Write-Host "No changed Python files." -ForegroundColor Green
} else {
  Write-Host "> Ruff changed files" -ForegroundColor Cyan
  & ruff check @files
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & ruff format --check @files
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "> Backend and launcher tests" -ForegroundColor Cyan
python -m pytest backend/tests launcher/tests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "> Frontend production build" -ForegroundColor Cyan
Push-Location frontend
try {
  npm run build
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
