param(
  [ValidateSet("start", "stop", "status", "doctor", "quality", "changed-quality", "security", "index", "memory", "architecture", "baseline", "bootstrap", "checkpoint")]
  [string]$Action = "status",
  [Parameter(Position=1, ValueFromRemainingArguments=$true)]
  [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked([string]$Command) {
  Write-Host "> $Command" -ForegroundColor Cyan
  Invoke-Expression $Command
  if ($LASTEXITCODE -ne 0) { throw "Command failed: $Command" }
}

switch ($Action) {
  "start" { Invoke-Checked "docker compose -f docker-compose.dev.yml up -d"; Invoke-Checked "docker compose -f docker-compose.dev.yml ps" }
  "stop" { Invoke-Checked "docker compose -f docker-compose.dev.yml stop" }
  "status" { Invoke-Checked "docker compose -f docker-compose.dev.yml ps" }
  "doctor" { & "$PSScriptRoot\lumina-doctor.ps1" }
  "quality" { & "$PSScriptRoot\lumina-quality.ps1" }
  "changed-quality" { & "$PSScriptRoot\lumina-changed-quality.ps1" }
  "security" { & "$PSScriptRoot\lumina-security.ps1" }
  "index" { Invoke-Checked "python scripts/ai/index_repository.py" }
  "memory" {
    if (-not $Arguments -or [string]::IsNullOrWhiteSpace(($Arguments -join " "))) { throw 'Usage: .\scripts\lumina-dev.ps1 memory "question"' }
    & "$PSScriptRoot\lumina-memory.ps1" -Query ($Arguments -join " ")
  }
  "architecture" { Invoke-Checked "python scripts/ai/architecture_inventory.py" }
  "baseline" { & "$PSScriptRoot\lumina-baseline.ps1" }
  "bootstrap" { & "$PSScriptRoot\lumina-bootstrap.ps1" }
  "checkpoint" { & "$PSScriptRoot\lumina-checkpoint.ps1" }
}
