# LUMINA Repository Agent

Before changing code:

1. Read `AI_AGENT_RULES.md`.
2. Query repository memory with `./scripts/lumina-dev.ps1 memory "<task and relevant module>"`.
3. Inspect the exact files returned by repository memory.
4. Create a Git checkpoint before broad multi-file changes.
5. Keep changes within the requested module.
6. Run `./scripts/lumina-dev.ps1 changed-quality` before completion.
7. Run `./scripts/lumina-dev.ps1 security` for authentication, file handling, subprocess, networking, dependency, or deployment changes.
8. Update architecture documentation when module boundaries or infrastructure change.

Never delete untracked files, backups, runtime evidence, or user content without explicit instruction.
