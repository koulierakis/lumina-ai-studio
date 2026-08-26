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
- persistent_task_store
"""

__version__ = "1.2.0"

# Install the bounded validation/test repair loop as part of normal package
# initialization. The installer is idempotent and preserves the existing
# TaskService architecture rather than replacing it.
from .autonomous_repair import install_automatic_repair

install_automatic_repair()

# Install durable task persistence before server.py imports the router's
# configure function. This keeps the public bootstrap API stable while making
# Code Builder task/recovery state survive backend restarts and PC reboots.
from .persistent_task_store import install_persistent_task_store

install_persistent_task_store()
