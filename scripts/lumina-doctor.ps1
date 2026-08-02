$ErrorActionPreference = "Continue"
$tools = @("git", "python", "node", "npm", "docker", "ollama", "aider", "ruff", "pre-commit", "semgrep", "trivy", "gitleaks", "ast-grep", "rg", "promptfoo")
foreach ($tool in $tools) {
  $cmd = Get-Command $tool -ErrorAction SilentlyContinue
  if ($cmd) { Write-Host ("[OK]   {0}" -f $tool) -ForegroundColor Green }
  else { Write-Host ("[MISS] {0}" -f $tool) -ForegroundColor Red }
}
Write-Host ""
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
Write-Host ""
try { Invoke-RestMethod http://127.0.0.1:6333/healthz | Out-Null; Write-Host "[OK]   Qdrant" -ForegroundColor Green } catch { Write-Host "[FAIL] Qdrant" -ForegroundColor Red }
try { Invoke-RestMethod http://127.0.0.1:11434/api/tags | Out-Null; Write-Host "[OK]   Ollama" -ForegroundColor Green } catch { Write-Host "[FAIL] Ollama" -ForegroundColor Red }
