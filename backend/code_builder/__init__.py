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
- patch_generation_service
- build_service
- history_service
- task_service
- persistent_task_store
- task_engine_integration
"""

__version__ = "1.4.0"

from .persistent_task_store import install_persistent_task_store
from .patch_generation_service import install_ai_patch_generation
from .task_engine_integration import install_task_engine_integration

install_persistent_task_store()
install_ai_patch_generation()
install_task_engine_integration()
