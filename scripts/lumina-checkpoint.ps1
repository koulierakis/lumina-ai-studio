$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$branch = (git branch --show-current).Trim()
$sha = (git rev-parse --short HEAD).Trim()
$tag = "lumina-checkpoint-$stamp"
git tag -a $tag -m "LUMINA checkpoint $stamp on $branch at $sha"
if ($LASTEXITCODE -ne 0) { throw "Checkpoint creation failed" }
Write-Host $tag
