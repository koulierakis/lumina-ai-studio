from __future__ import annotations

from typing import Protocol

from .applier import ProposedFileChange
from .models import ChangePlan, TaskRequest


class ChangeGenerator(Protocol):
    def generate(
        self,
        request: TaskRequest,
        plan: ChangePlan,
        file_context: dict[str, str],
    ) -> list[ProposedFileChange]:
        """Generate the exact file transaction required by an approved plan."""
