"""User-facing and internal launcher error types."""
from __future__ import annotations


class LauncherError(Exception):
    """Base launcher error with a clear user message."""

    def __init__(self, message: str, *, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class AlreadyRunningError(LauncherError):
    def __init__(self, message: str = "LUMINA is already running.") -> None:
        super().__init__(message, code=2)


class DependencyMissingError(LauncherError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=3)


class PortInUseError(LauncherError):
    def __init__(self, service: str, port: int) -> None:
        super().__init__(
            f"The {service} port {port} is already in use by another process. "
            "Stop that process or change the port in runtime settings.",
            code=4,
        )


class StartupTimeoutError(LauncherError):
    def __init__(self, service: str) -> None:
        super().__init__(
            f"{service} did not become ready before the startup timeout. "
            "Check .lumina-runtime/logs for details.",
            code=5,
        )


class ShutdownError(LauncherError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=6)
