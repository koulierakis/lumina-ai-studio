"""Provider-neutral, route-free orchestration and deterministic validation."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
    MalformedDocumentAIResponse,
)
from .groq_provider import (
    GroqDocumentProvider,
    GroqProviderHTTPError,
    GroqProviderUnavailable,
)
from .models import CompanyProfile, NaturalDocumentCreationRequest
from .natural_creation import (
    NaturalCreationProviderError,
    NaturalCreationResult,
    NaturalProviderOutput,
    create_natural_document,
)
from .ollama_adapter import OllamaDocumentAdapter, get_ollama_adapter

DEFAULT_PROVIDER = "ollama"
SUPPORTED_PROVIDERS = frozenset({"ollama", "groq"})


class UnknownDocumentAIProvider(DocumentAIProviderError):
    """Raised when provider selection is outside the fixed allowlist."""


class GenerationValidationError(DocumentAIProviderError):
    """Raised when typed output fails deterministic safety validation."""


class GenerationFallbackError(DocumentAIProviderError):
    """Raised when an explicitly selected fallback provider also fails."""


class GenerationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_provider: str
    provider_used: str
    fallback_used: bool = False
    fallback_from: str | None = None
    validation_status: Literal["passed"] = "passed"
    verified_fact_coverage: dict[str, list[str]] = Field(default_factory=dict)
    generated_claim_count: int = 0
    unsupported_claim_count: int = 0
    placeholder_status: dict[str, Any] = Field(default_factory=dict)
    elapsed_milliseconds: int = 0
    attempt_count: int = 1


class OrchestratedGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: NaturalCreationResult
    metadata: GenerationMetadata


class OllamaNaturalDocumentProvider(DocumentAIProvider):
    """Strict provider bridge over the accepted lazy Ollama adapter."""

    name = "ollama"

    def __init__(self, adapter: OllamaDocumentAdapter | None = None) -> None:
        self._adapter = adapter

    @property
    def adapter(self) -> OllamaDocumentAdapter:
        return self._adapter or get_ollama_adapter()

    async def status(self) -> dict[str, Any]:
        status = await self.adapter.check_availability()
        return {"name": self.name, "configured": True, **status}

    async def generate_document(
        self, request: str, context: dict[str, Any]
    ) -> NaturalProviderOutput:
        result = await self.adapter.generate_structured_document(
            json.dumps({"request": request, "context": context}, ensure_ascii=False),
            timeout_seconds=float(context.get("timeout_seconds", 90.0)),
        )
        if not result.success:
            if result.error and "timed out" in result.error.casefold():
                raise DocumentAIProviderTimeout("Ollama generation timed out")
            raise DocumentAIProviderError("Ollama generation failed")
        try:
            payload = json.loads(result.content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MalformedDocumentAIResponse(
                "Ollama returned malformed structured content"
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedDocumentAIResponse("Ollama structured content must be an object")
        try:
            return NaturalProviderOutput.model_validate(payload, strict=True)
        except ValueError as exc:
            raise MalformedDocumentAIResponse(
                "Ollama returned invalid typed document output"
            ) from exc


class DocumentAIProviderRegistry:
    """Fixed-name provider registry; it never imports user-selected code."""

    def __init__(self, providers: dict[str, DocumentAIProvider] | None = None) -> None:
        self._providers = dict(providers or {})
        unknown = set(self._providers) - SUPPORTED_PROVIDERS
        if unknown:
            raise UnknownDocumentAIProvider(
                f"Unsupported document AI provider: {sorted(unknown)[0]}"
            )

    def get(self, name: str | None = None) -> DocumentAIProvider:
        selected = (name or DEFAULT_PROVIDER).strip().casefold()
        if selected not in SUPPORTED_PROVIDERS:
            raise UnknownDocumentAIProvider(
                f"Unsupported document AI provider: {selected or '<empty>'}"
            )
        if selected in self._providers:
            return self._providers[selected]
        if selected == "groq":
            provider: DocumentAIProvider = GroqDocumentProvider()
        else:
            provider = OllamaNaturalDocumentProvider()
        self._providers[selected] = provider
        return provider


def _normalize_placeholder(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value).strip("[] ").upper()).strip("_")


def validate_placeholder_integrity(generation: NaturalCreationResult) -> dict[str, Any]:
    content = generation.document.content
    found = {
        _normalize_placeholder(value)
        for value in re.findall(r"\[([^\]]+)\]", content)
        if _normalize_placeholder(value)
    }
    declared = {
        _normalize_placeholder(value)
        for value in generation.document.unresolved_fields
        if _normalize_placeholder(value)
    }
    required = {
        _normalize_placeholder(value)
        for value in generation.intentional_blank_fields
        if _normalize_placeholder(value)
    }
    missing_required = sorted(required - found)
    undeclared = sorted(found - declared)
    declared_but_absent = sorted(declared - found)
    if missing_required or undeclared or declared_but_absent:
        raise GenerationValidationError(
            "Generated document failed placeholder integrity validation"
        )
    return {
        "valid": True,
        "required": sorted(required),
        "found": sorted(found),
        "declared": sorted(declared),
        "missing_required": [],
        "undeclared": [],
        "declared_but_absent": [],
    }


def _normalized_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).casefold()
    return " ".join(str(value).casefold().split())


def verified_fact_coverage(generation: NaturalCreationResult) -> dict[str, list[str]]:
    content = generation.document.content.casefold()
    verified_claims = {
        claim.field_name: claim.value.casefold()
        for claim in generation.document.claims
        if claim.origin == "verified"
    }
    covered: list[str] = []
    omitted: list[str] = []
    for field_name, value in generation.verified_facts.items():
        normalized = _normalized_value(value)
        claim_value = verified_claims.get(field_name)
        if normalized and (normalized in content or claim_value == normalized):
            covered.append(field_name)
        else:
            omitted.append(field_name)
    return {
        "supplied": list(generation.verified_facts),
        "covered": covered,
        "omitted": omitted,
    }


HIGH_RISK_FIELDS = {
    "company_name",
    "legal_form",
    "jurisdiction",
    "registration_number",
    "registered_office",
    "principal_office",
    "beneficial_owners",
    "members",
    "directors",
    "managers",
    "authorized_signatories",
    "licence",
    "license",
    "regulatory_status",
    "bank_account",
    "iban",
    "swift",
    "amount",
    "source_of_funds",
    "source_of_wealth",
    "expected_account_activity",
}

HIGH_RISK_TEXT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("financial amount", r"(?:EUR|USD|GBP|€|\$|£)\s*[\d,.]+"),
    ("bank account", r"\b(?:IBAN|SWIFT|BIC)\s*[:#]?\s*[A-Z0-9]{6,}\b"),
    (
        "registration",
        r"\b(?:registration|company)\s+(?:number|no\.?|#)\s*[:#]?\s*[A-Z0-9][A-Z0-9 ./-]{4,}",
    ),
    ("regulatory status", r"\b(?:licensed|regulated|authorized|certified)\s+by\b"),
    ("ownership", r"\b(?:owned|controlled)\s+by\b"),
    ("address", r"\bregistered office\s+(?:is|at|:)\s*[^\[]+"),
    ("source of funds", r"\bsource of funds\s+(?:is|:|derives? from)\s*[^\[]+"),
    ("source of wealth", r"\bsource of wealth\s+(?:is|:|derives? from)\s*[^\[]+"),
    ("account activity", r"\bexpected account activity\s+(?:is|:|includes?)\s*[^\[]+"),
)


def detect_unsupported_claims(generation: NaturalCreationResult) -> list[str]:
    supported_values = {
        _normalized_value(value)
        for value in (
            *generation.verified_facts.values(),
            *generation.user_supplied_facts.values(),
        )
        if _normalized_value(value)
    }
    violations: list[str] = []
    for claim in generation.generated_claims:
        normalized_field = claim.field_name.casefold().replace(" ", "_")
        normalized_value = _normalized_value(claim.value)
        if normalized_field in HIGH_RISK_FIELDS and normalized_value not in supported_values:
            violations.append(f"unsupported generated claim: {claim.field_name}")

    content = generation.document.content
    for category, pattern in HIGH_RISK_TEXT_PATTERNS:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            excerpt = match.group(0)
            if "[" in excerpt or "]" in excerpt:
                continue
            normalized = _normalized_value(excerpt)
            if not any(value and value in normalized for value in supported_values):
                violations.append(f"unsupported {category} claim")
                break
    return list(dict.fromkeys(violations))


def validate_generation(generation: NaturalCreationResult) -> dict[str, Any]:
    placeholder_status = validate_placeholder_integrity(generation)
    unsupported = detect_unsupported_claims(generation)
    if unsupported:
        raise GenerationValidationError("Generated document contains unsupported high-risk claims")
    return {
        "placeholder_status": placeholder_status,
        "coverage": verified_fact_coverage(generation),
        "unsupported": unsupported,
    }


def _eligible_fallback_failure(exc: Exception) -> bool:
    if isinstance(exc, DocumentAIProviderTimeout):
        return True
    if isinstance(exc, NaturalCreationProviderError):
        cause = exc.__cause__
        return (
            isinstance(cause, (DocumentAIProviderTimeout, GroqProviderUnavailable))
            or isinstance(cause, GroqProviderHTTPError)
            and cause.retryable
        )
    return False


async def generate_document(
    request: NaturalDocumentCreationRequest,
    profile: CompanyProfile,
    *,
    provider_name: str | None = None,
    fallback_provider_name: str | None = None,
    registry: DocumentAIProviderRegistry | None = None,
    timeout_seconds: float = 90.0,
) -> OrchestratedGenerationResult:
    """Invoke one selected provider and an optional explicit fallback provider."""
    provider_registry = registry or DocumentAIProviderRegistry()
    requested_name = (provider_name or DEFAULT_PROVIDER).strip().casefold()
    primary = provider_registry.get(requested_name)
    started_at = time.monotonic()
    fallback_used = False
    fallback_from: str | None = None
    attempt_count = 1

    try:
        generation = await create_natural_document(
            request, profile, primary, timeout_seconds=timeout_seconds
        )
        provider_used = requested_name
    except Exception as primary_error:
        if not fallback_provider_name or not _eligible_fallback_failure(primary_error):
            raise
        fallback_name = fallback_provider_name.strip().casefold()
        if fallback_name == requested_name:
            raise GenerationFallbackError(
                "Fallback provider must differ from the selected provider"
            ) from primary_error
        fallback = provider_registry.get(fallback_name)
        fallback_used = True
        fallback_from = requested_name
        attempt_count = 2
        try:
            generation = await create_natural_document(
                request, profile, fallback, timeout_seconds=timeout_seconds
            )
            provider_used = fallback_name
        except Exception as fallback_error:
            raise GenerationFallbackError(
                f"Explicit fallback provider '{fallback_name}' failed"
            ) from fallback_error

    validation = validate_generation(generation)
    elapsed_ms = max(round((time.monotonic() - started_at) * 1000), 0)
    return OrchestratedGenerationResult(
        generation=generation,
        metadata=GenerationMetadata(
            requested_provider=requested_name,
            provider_used=provider_used,
            fallback_used=fallback_used,
            fallback_from=fallback_from,
            verified_fact_coverage=validation["coverage"],
            generated_claim_count=len(generation.generated_claims),
            unsupported_claim_count=len(validation["unsupported"]),
            placeholder_status=validation["placeholder_status"],
            elapsed_milliseconds=elapsed_ms,
            attempt_count=attempt_count,
        ),
    )
