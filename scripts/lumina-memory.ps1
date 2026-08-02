param(
  [Parameter(Position=0)]
  [string]$Query,
  [int]$Limit = 8,
  [switch]$Full
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if ([string]::IsNullOrWhiteSpace($Query)) { throw 'Usage: .\scripts\lumina-memory.ps1 "your question"' }
$argsList = @("scripts/ai/query_repository.py", $Query, "--limit", "$Limit")
if ($Full) { $argsList += "--full" }
python @argsList
