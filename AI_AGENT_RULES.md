# LUMINA AI Agent Rules

1. Work only inside the repository root.
2. Never delete or overwrite user data, media, databases, credentials, or runtime state.
3. Never execute `git reset --hard`, `git clean -fdx`, destructive migrations, or recursive deletion without an explicit task requiring it.
4. Create a Git checkpoint before multi-file changes.
5. Prefer minimal, reversible patches.
6. Preserve API compatibility unless the task explicitly requires a breaking change.
7. Never expose secrets from `.env` files in logs, prompts, tests, commits, or documentation.
8. Run targeted tests after each logical change and the full quality gate before completion.
9. Do not modify generated model weights, `_local_models`, `_tools`, runtime databases, uploads, outputs, or backups.
10. Record architecture-impacting decisions in `docs/architecture/adr/`.
11. A task is complete only when code, tests, documentation, and rollback notes are consistent.
