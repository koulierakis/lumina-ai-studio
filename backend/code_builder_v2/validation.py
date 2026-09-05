from __future__ import annotations

from dataclasses import dataclass

from .executor import CommandExecutor, CommandResult


class ValidationError(RuntimeError):
    def __init__(self, result: CommandResult):
        self.result = result
        super().__init__(f"Validation command failed ({result.returncode}): {result.command}")


@dataclass(slots=True)
class ValidationRunner:
    executor: CommandExecutor

    def run(self, commands: list[str], timeout_seconds: int) -> list[CommandResult]:
        results: list[CommandResult] = []
        if not commands:
            return results
        per_command_timeout = max(1, timeout_seconds // max(1, len(commands)))
        for command in commands:
            result = self.executor.run(command, per_command_timeout)
            results.append(result)
            if result.returncode != 0:
                raise ValidationError(result)
        return results
