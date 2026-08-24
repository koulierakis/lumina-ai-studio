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
- autonomous_repair
"""

__version__ = "1.1.0"

# Install the bounded validation/test repair loop as part of normal package
# initialization.  The installer is idempotent and preserves the existing
# TaskService architecture rather than replacing it.
from .autonomous_repair import install_automatic_repair

install_automatic_repair()
