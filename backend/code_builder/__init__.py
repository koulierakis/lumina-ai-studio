"""
LUMINA Code Builder

This package contains all backend services required by the
LUMINA Code Builder.

Modules include:

- backup_service
- repository_service
- security
- context_service
- planning_service
- ollama_service
- validation_service
- patch_service
- build_service
- history_service
- task_service
- persistent_task_store
"""

__version__ = "1.2.0"

from .persistent_task_store import install_persistent_task_store

install_persistent_task_store()