# ADR 0001: Local AI Development Environment

Status: Accepted

LUMINA uses Ollama for local inference, Roo Code as the primary VS Code agent, Aider for Git-aware editing, Qdrant for repository memory, and deterministic quality/security gates before completion. Docker Compose defines supporting infrastructure. Agent changes remain reversible through Git checkpoints.
