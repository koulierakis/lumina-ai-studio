$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$failed = $false

gitleaks detect --source . --redact --no-banner
if ($LASTEXITCODE -ne 0) { $failed = $true }
semgrep scan --config auto backend frontend/src launcher
if ($LASTEXITCODE -ne 0) { $failed = $true }
trivy fs --scanners vuln,secret,misconfig --skip-dirs node_modules --skip-dirs .git --skip-dirs _local_models .
if ($LASTEXITCODE -ne 0) { $failed = $true }
if ($failed) { exit 1 }
