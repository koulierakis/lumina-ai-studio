"""Route-independent interpretation and typed natural document creation."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
    MalformedDocumentAIResponse,
)
from .models import CompanyProfile, NaturalDocumentCreationRequest


class NaturalCreationError(RuntimeError):
    """Base failure for route-independent natural document creation."""


class InvalidNaturalCreationRequest(NaturalCreationError):
    """Raised when a natural-language request has no usable objective."""


class NaturalCreationProviderError(NaturalCreationError):
    """Raised when the selected provider fails explicitly."""


class NaturalDocumentClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field_name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    origin: Literal["verified", "user", "generated"]


class NaturalProviderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    category: str = Field(min_length=1)
    language: str = Field(min_length=2)
    content: str = Field(min_length=1)
    claims: list[NaturalDocumentClaim] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)


class NaturalCreationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["created"] = "created"
    original_request: str
    document: NaturalProviderOutput
    verified_facts: dict[str, Any] = Field(default_factory=dict)
    fact_provenance: dict[str, list[dict]] = Field(default_factory=dict)
    user_supplied_facts: dict[str, Any] = Field(default_factory=dict)
    generated_claims: list[NaturalDocumentClaim] = Field(default_factory=list)
    intentional_blank_fields: list[str] = Field(default_factory=list)
    review_status: str = "DRAFT_REVIEW"
    official_document_safety: str = "not_applicable"


BLANK_ALIASES = {
    "parties": ["PARTY A", "PARTY B"],
    "party details": ["PARTY A", "PARTY B"],
    "company details": ["COMPANY A DETAILS", "COMPANY B DETAILS"],
    "other company": ["SECOND PARTY"],
    "another company": ["SECOND PARTY"],
    "second party": ["SECOND PARTY"],
    "client details": ["CLIENT DETAILS"],
    "client": ["CLIENT"],
    "service provider": ["SERVICE PROVIDER"],
    "fee": ["FEE"],
    "payment schedule": ["PAYMENT SCHEDULE"],
    "payment details": ["PAYMENT DETAILS"],
    "effective date": ["EFFECTIVE DATE"],
    "governing law": ["GOVERNING LAW"],
    "amount": ["AMOUNT"],
    "payment date": ["PAYMENT DATE"],
    "invoice number": ["INVOICE NUMBER"],
}

DOCUMENT_TYPES: tuple[tuple[str, str, str, str], ...] = (
    (r"\b(?:non[- ]disclosure|nda)\b", "nda", "Non-Disclosure Agreement", "Legal"),
    (r"\bservice agreement\b", "service_agreement", "Service Agreement", "Legal"),
    (r"\bpayment agreement\b", "payment_agreement", "Payment Agreement", "Legal"),
    (r"\bconsulting agreement\b", "consulting_agreement", "Consulting Agreement", "Legal"),
    (r"\bcommission agreement\b", "commission_agreement", "Commission Agreement", "Legal"),
    (r"\binvoice\b", "invoice", "Invoice", "Commercial"),
    (
        r"\bbusiness nature\b",
        "business_nature_operating_model",
        "Business Nature & Operating Model Statement",
        "Banking/KYC",
    ),
    (r"\b(?:board|corporate) resolution\b", "board_resolution", "Board Resolution", "Corporate"),
)

PROFILE_FACT_FIELDS = (
    "company_name",
    "legal_form",
    "jurisdiction",
    "registration_number",
    "formation_date",
    "registered_office",
    "principal_office",
    "business_activities",
    "business_model",
    "source_of_funds",
    "source_of_wealth",
    "expected_account_activity",
    "organizational_structure",
    "aml_controls",
)


def _classify_request(request: str, requested_type: str | None = None) -> dict[str, str]:
    if requested_type and requested_type not in {"custom", "automatic"}:
        key = re.sub(r"[^a-z0-9]+", "_", requested_type.casefold()).strip("_")
        return {
            "key": key or "custom_document",
            "title": requested_type.replace("_", " ").title(),
            "category": "General",
        }
    for pattern, key, title, category in DOCUMENT_TYPES:
        if re.search(pattern, request, re.IGNORECASE):
            return {"key": key, "title": title, "category": category}
    return {"key": "custom_document", "title": "Custom Document", "category": "General"}


def _requested_blanks(request: str) -> list[str]:
    lowered = request.casefold()
    if not re.search(r"\b(?:leave|keep)\b.{0,120}\bblank\b", lowered):
        return []
    fields: list[str] = []
    for phrase, aliases in BLANK_ALIASES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            fields.extend(aliases)
    return list(dict.fromkeys(fields))


def _user_supplied_facts(request: str, intentional_blanks: list[str]) -> dict[str, Any]:
    patterns = {
        "commission_percentage": r"\bcommission(?:\s+(?:percentage|rate))?\s*(?:is|of|:)\s*(\d+(?:\.\d+)?\s*%)",
        "invoice_number": r"\binvoice\s+(?:number|no\.?|#)\s*(?:is|:)?\s*([A-Z0-9][A-Z0-9./-]+)",
        "payment_date": r"\bpayment\s+date\s+(?:is|:|of)\s*([A-Za-z0-9, /-]+?)(?:[.;]|$)",
        "amount": r"\bamount\s*(?:is|:|of)\s*((?:EUR|USD|GBP|€|\$|£)\s*[\d,.]+|[\d,.]+\s*(?:EUR|USD|GBP))",
        "client": r"\bclient\s*:\s*([^\n.;]+)",
        "service_description": r"\bservice\s*:\s*([^\n.;]+)",
    }
    facts: dict[str, Any] = {}
    blank_keys = {field.replace(" ", "_") for field in intentional_blanks}
    for field_name, pattern in patterns.items():
        if field_name.upper() in intentional_blanks or field_name.upper() in blank_keys:
            continue
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            value = match.group(1).strip().rstrip(".;")
            if value.casefold() not in {"blank", "unknown", "unresolved", "not provided"}:
                facts[field_name] = value
    return facts


def interpret_natural_document_request(
    request: str, profile: CompanyProfile, requested_type: str | None = None
) -> dict[str, Any]:
    """Interpret only explicit request text without generating or persisting content."""
    clean = " ".join(str(request or "").split())
    if not clean:
        raise InvalidNaturalCreationRequest("A document objective is required")
    if re.fullmatch(r"(?:please\s+)?create\s+(?:an?\s+)?agreement[.!]?", clean, re.I):
        return {
            "status": "needs_clarification",
            "clarification_question": (
                "What kind of agreement do you need (for example, payment, services, "
                "commission, consulting, or NDA)?"
            ),
        }

    classification = _classify_request(clean, requested_type)
    official_template = bool(
        re.search(
            r"\b(?:birth certificate|death certificate|passport|court order|police certificate|government certificate|official certificate)\b",
            clean,
            re.I,
        )
    ) and not re.search(r"\b(?:authentic source|uploaded source|source document)\b", clean, re.I)
    intentional = _requested_blanks(clean)
    legal_draft = classification["category"] in {"Legal", "Corporate"}
    return {
        "status": "ready",
        "document_type": classification["key"],
        "document_title": (
            f"{classification['title']} Template" if official_template else classification["title"]
        ),
        "category": classification["category"],
        "intentional_blank_fields": intentional,
        "user_supplied_facts": _user_supplied_facts(clean, intentional),
        "review_status": "LEGAL_REVIEW_RECOMMENDED" if legal_draft else "DRAFT_REVIEW",
        "original_request": clean,
        "official_document_safety": "template_only" if official_template else "not_applicable",
        "profile_selected": bool(profile.id),
    }


def _verified_profile_facts(profile: CompanyProfile) -> dict[str, Any]:
    return {
        field_name: value
        for field_name in PROFILE_FACT_FIELDS
        if (value := getattr(profile, field_name, None)) not in (None, "", [], {})
    }


def _provider_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, NaturalProviderOutput):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump()
        if isinstance(payload, dict):
            return payload
    raise MalformedDocumentAIResponse("Provider output must be a structured object")


def _validate_claim_origins(
    document: NaturalProviderOutput,
    verified_facts: dict[str, Any],
    user_facts: dict[str, Any],
) -> list[NaturalDocumentClaim]:
    generated: list[NaturalDocumentClaim] = []
    for claim in document.claims:
        if claim.origin == "verified":
            expected = verified_facts.get(claim.field_name)
            if (
                expected is None
                or str(expected).strip().casefold() != claim.value.strip().casefold()
            ):
                raise MalformedDocumentAIResponse(
                    f"Provider marked an unsupported claim as verified: {claim.field_name}"
                )
        elif claim.origin == "user":
            expected = user_facts.get(claim.field_name)
            if (
                expected is None
                or str(expected).strip().casefold() != claim.value.strip().casefold()
            ):
                raise MalformedDocumentAIResponse(
                    f"Provider marked an unsupported claim as user supplied: {claim.field_name}"
                )
        else:
            generated.append(claim)
    return generated


async def create_natural_document(
    request: NaturalDocumentCreationRequest,
    profile: CompanyProfile,
    provider: DocumentAIProvider,
    *,
    timeout_seconds: float = 90.0,
) -> NaturalCreationResult:
    """Create typed draft content without mutating verified facts or persistence."""
    interpretation = interpret_natural_document_request(
        request.request, profile, request.requested_type
    )
    if interpretation["status"] != "ready":
        raise InvalidNaturalCreationRequest(interpretation["clarification_question"])
    verified_facts = _verified_profile_facts(profile)
    user_facts = interpretation["user_supplied_facts"]
    context = {
        "document_type": interpretation["document_type"],
        "document_title": interpretation["document_title"],
        "category": interpretation["category"],
        "language": request.language,
        "tone": request.tone,
        "style": request.style,
        "verified_facts": verified_facts,
        "fact_provenance": profile.fact_provenance,
        "user_supplied_facts": user_facts,
        "intentional_blank_fields": interpretation["intentional_blank_fields"],
        "fact_safety": (
            "Do not invent or relabel legal, compliance, financial, identity, banking, "
            "regulatory, or corporate facts. Mark unsupported content as generated."
        ),
    }
    bounded_timeout = min(max(float(timeout_seconds), 0.1), 180.0)
    try:
        raw_output = await asyncio.wait_for(
            provider.generate_document(interpretation["original_request"], context),
            timeout=bounded_timeout,
        )
    except TimeoutError as exc:
        raise DocumentAIProviderTimeout(
            f"Natural document provider timed out after {bounded_timeout:g}s"
        ) from exc
    except DocumentAIProviderTimeout:
        raise
    except DocumentAIProviderError as exc:
        raise NaturalCreationProviderError(str(exc)) from exc
    except Exception as exc:
        raise NaturalCreationProviderError(
            f"Natural document provider failed: {type(exc).__name__}"
        ) from exc

    try:
        document = NaturalProviderOutput.model_validate(_provider_payload(raw_output), strict=True)
    except ValidationError as exc:
        raise MalformedDocumentAIResponse(
            "Provider returned malformed natural document output"
        ) from exc
    if document.document_type != interpretation["document_type"]:
        raise MalformedDocumentAIResponse("Provider changed the interpreted document type")
    generated_claims = _validate_claim_origins(document, verified_facts, user_facts)
    return NaturalCreationResult(
        original_request=interpretation["original_request"],
        document=document,
        verified_facts=verified_facts,
        fact_provenance=profile.fact_provenance,
        user_supplied_facts=user_facts,
        generated_claims=generated_claims,
        intentional_blank_fields=interpretation["intentional_blank_fields"],
        review_status=interpretation["review_status"],
        official_document_safety=interpretation["official_document_safety"],
    )


def ensure_intentional_placeholders(content: str, fields: list[str]) -> tuple[str, list[str]]:
    missing = [field for field in fields if f"[{field}]" not in content]
    return content, missing
