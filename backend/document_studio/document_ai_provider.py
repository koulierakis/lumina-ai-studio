"""Provider-neutral contracts for Document Studio AI implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DocumentAIProviderError(RuntimeError):
    """Base exception raised by a Document Studio AI provider."""


class DocumentAIProviderTimeout(DocumentAIProviderError):
    """Raised when a provider exceeds its bounded execution time."""


class MalformedDocumentAIResponse(DocumentAIProviderError):
    """Raised when a provider response does not implement the expected contract."""


def _required_attribute(value: Any, attribute: str) -> Any:
    result = getattr(value, attribute, None)
    if result is None:
        raise MalformedDocumentAIResponse(
            f"Provider response is missing required attribute: {attribute}"
        )
    return result


class DocumentAIProvider(ABC):
    """Replaceable, route-independent Document Studio AI provider."""

    name: str

    @abstractmethod
    async def generate_document(self, request: str, context: dict[str, Any]) -> Any:
        """Return a provider-specific canonical document object."""

    async def analyze_intent(self, request: str, context: dict[str, Any]) -> Any:
        document = await self.generate_document(request, context)
        return _required_attribute(document, "intent")

    async def revise_document(self, instruction: str, context: dict[str, Any]) -> Any:
        return await self.generate_document(instruction, context)

    async def regenerate_section(self, instruction: str, context: dict[str, Any]) -> list[Any]:
        document = await self.generate_document(instruction, context)
        blocks = _required_attribute(document, "blocks")
        if not isinstance(blocks, list):
            raise MalformedDocumentAIResponse("Provider response blocks must be a list")
        return blocks

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        """Return a credential-free provider availability summary."""
