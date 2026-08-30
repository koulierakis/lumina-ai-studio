"""Deterministic, route-independent Document Studio pack recommendations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import (
    CompanyProfile,
    DocumentRecommendation,
    PackAdvisorRequest,
    PackAdvisorResponse,
)

# Snapshot of the canonical identifiers currently defined by Document Studio's
# service registry. Keeping the planner independent avoids importing service or
# any rendering/export dependencies. A compatibility test guards registry drift.
CURRENT_DOCUMENT_TYPES = frozenset(
    {
        "certificate_of_authority",
        "certificate_of_incumbency",
        "corporate_resolution",
        "board_resolution",
        "shareholders_resolution",
        "banking_cover_letter",
        "cover_letter",
        "aml_declaration",
        "ubo_declaration",
        "kyc_declaration",
        "source_of_funds_declaration",
        "company_profile",
        "invoice",
        "proforma_invoice",
        "consulting_agreement",
        "agency_agreement",
        "commission_agreement",
        "nda",
        "ncnDA",
        "imfpa",
        "fee_protection_agreement",
        "power_of_attorney",
        "affidavit",
        "memorandum",
        "compliance_letter",
    }
)

CORE_COMPANY_FIELDS = (
    "company_name",
    "legal_form",
    "jurisdiction",
    "registration_number",
    "registered_office",
)

FIELD_LABELS = {
    "company_name": "company name",
    "legal_form": "legal form",
    "jurisdiction": "jurisdiction",
    "registration_number": "registration number",
    "registered_office": "registered office",
    "business_activities": "business activities",
    "business_model": "business model",
    "source_of_funds": "source of funds",
    "source_of_wealth": "source of wealth",
    "expected_account_activity": "expected account activity",
    "organizational_structure": "organizational structure",
    "aml_controls": "AML controls",
    "beneficial_owners": "beneficial owners or members",
    "authorized_signatories": "authorized signatories",
    "directors": "directors or managers",
}


@dataclass(frozen=True)
class RecommendationRule:
    document_type: str
    title: str
    reason: str
    priority: str
    required_fields: tuple[str, ...] = ()
    any_of_fields: tuple[tuple[str, ...], ...] = ()


def _has_value(value) -> bool:
    return value not in (None, "", [], {})


def _missing_data(profile: CompanyProfile, rule: RecommendationRule) -> list[str]:
    missing = [
        FIELD_LABELS.get(field_name, field_name.replace("_", " "))
        for field_name in rule.required_fields
        if not _has_value(getattr(profile, field_name, None))
    ]
    for alternatives in rule.any_of_fields:
        if not any(_has_value(getattr(profile, field_name, None)) for field_name in alternatives):
            label = FIELD_LABELS.get(alternatives[0], " or ".join(alternatives))
            if label not in missing:
                missing.append(label)
    return missing


def _banking_rules(enhanced: bool) -> tuple[RecommendationRule, ...]:
    rules = [
        RecommendationRule(
            "company_profile",
            "Corporate Profile and Business Overview",
            "Provides the core company identity and operating overview used during onboarding.",
            "required",
            CORE_COMPANY_FIELDS + ("business_activities", "business_model"),
        ),
        RecommendationRule(
            "source_of_funds_declaration",
            "Source of Funds Declaration",
            "Explains the declared origin of funds without inferring financial amounts.",
            "required",
            CORE_COMPANY_FIELDS + ("source_of_funds",),
        ),
        RecommendationRule(
            "kyc_declaration",
            "KYC and Expected Account Activity Declaration",
            "Records the supplied customer profile and expected account activity.",
            "required",
            CORE_COMPANY_FIELDS + ("expected_account_activity",),
        ),
        RecommendationRule(
            "ubo_declaration",
            "UBO Declaration",
            "Documents reviewed ownership information required for beneficial-owner checks.",
            "required",
            CORE_COMPANY_FIELDS,
            (("beneficial_owners", "members"),),
        ),
        RecommendationRule(
            "certificate_of_authority",
            "Certificate of Authority",
            "Identifies reviewed representatives authorized to act for the company.",
            "required",
            CORE_COMPANY_FIELDS,
            (("authorized_signatories",), ("directors", "managers")),
        ),
        RecommendationRule(
            "corporate_resolution",
            "Corporate Resolution for Banking",
            "Records the internal authorization for the proposed banking relationship.",
            "required",
            CORE_COMPANY_FIELDS,
            (("directors", "managers"), ("authorized_signatories",)),
        ),
        RecommendationRule(
            "banking_cover_letter",
            "Banking Cover Letter",
            "Introduces the company and states the onboarding objective.",
            "optional",
            ("company_name", "registered_office"),
        ),
    ]
    if enhanced:
        rules.extend(
            [
                RecommendationRule(
                    "aml_declaration",
                    "Enhanced AML Information Declaration",
                    "Supplies reviewed AML controls for enhanced due diligence.",
                    "optional",
                    CORE_COMPANY_FIELDS + ("aml_controls",),
                ),
                RecommendationRule(
                    "compliance_letter",
                    "Source of Wealth and Compliance Letter",
                    "Summarizes supplied source-of-wealth and organizational information.",
                    "optional",
                    CORE_COMPANY_FIELDS + ("source_of_wealth", "organizational_structure"),
                ),
                RecommendationRule(
                    "certificate_of_incumbency",
                    "Certificate of Incumbency",
                    "Provides a reviewed summary of current company representatives.",
                    "optional",
                    CORE_COMPANY_FIELDS,
                    (("directors", "managers"),),
                ),
            ]
        )
    return tuple(rules)


def _objective_category(objective: str) -> tuple[str, bool]:
    normalized = " ".join(objective.casefold().split())
    enhanced = bool(
        re.search(
            r"(?<!\w)(?:enhanced|edd|comprehensive|complete|ενισχυμέν(?:ο|η|ησ)|πλήρ(?:ες|η)|ολοκληρωμέν(?:ο|η))(?!\w)",
            normalized,
        )
    )
    if re.search(
        r"(?<!\w)(?:bank account|banking|kyc|know your customer|due diligence|onboarding|τραπεζικ(?:ό|ος|ή)|τραπεζικό λογαριασμό|άνοιγμα λογαριασμού|δέουσα επιμέλεια)(?!\w)",
        normalized,
    ):
        return "banking", enhanced
    if re.search(
        r"(?<!\w)(?:board|shareholder|governance|corporate resolution|διοικητικό συμβούλιο|μέτοχ(?:ος|οι|ων)|εταιρική διακυβέρνηση|εταιρική απόφαση)(?!\w)",
        normalized,
    ):
        return "corporate", False
    if re.search(
        r"(?<!\w)(?:consulting|agency|commission|confidential|nda|agreement|συμβουλευτικ(?:ή|ές)|αντιπροσώπευση|προμήθεια|εμπιστευτικ\w*|εχεμύθ\w*|συμφωνία|σύμβαση)(?!\w)",
        normalized,
    ):
        return "legal", False
    return "general", False


def _rules_for_objective(objective: str) -> tuple[str, tuple[RecommendationRule, ...]]:
    category, enhanced = _objective_category(objective)
    if category == "banking":
        return category, _banking_rules(enhanced)
    if category == "corporate":
        return category, (
            RecommendationRule(
                "corporate_resolution",
                "Corporate Resolution",
                "Records the requested corporate decision.",
                "required",
                CORE_COMPANY_FIELDS,
                (("directors", "managers"),),
            ),
            RecommendationRule(
                "certificate_of_incumbency",
                "Certificate of Incumbency",
                "Summarizes reviewed current representatives where supporting evidence exists.",
                "optional",
                CORE_COMPANY_FIELDS,
                (("directors", "managers"),),
            ),
        )
    if category == "legal":
        normalized = objective.casefold()
        document_type, title = (
            ("nda", "Non-Disclosure Agreement")
            if re.search(r"(?<!\w)(?:confidential|nda|non[- ]disclosure|εμπιστευτικ\w*|εχεμύθ\w*)(?!\w)", normalized)
            else ("consulting_agreement", "Consulting Agreement")
            if re.search(r"consult|συμβουλευ", normalized)
            else ("agency_agreement", "Agency Agreement")
            if re.search(r"agency|αντιπροσώπ", normalized)
            else ("commission_agreement", "Commission Agreement")
            if re.search(r"commission|προμήθεια", normalized)
            else ("memorandum", "Business Memorandum")
        )
        return category, (
            RecommendationRule(
                document_type,
                title,
                "Documents the stated business or legal objective using supplied party facts.",
                "required",
                ("company_name",),
            ),
        )
    return category, (
        RecommendationRule(
            "company_profile",
            "Corporate Profile",
            "Provides a reusable summary of supplied company information.",
            "required",
            ("company_name", "legal_form", "jurisdiction"),
        ),
    )


def advise_documents(
    request: PackAdvisorRequest | str, profile: CompanyProfile
) -> PackAdvisorResponse:
    """Return deterministic recommendations; never generate or persist documents."""
    objective = request.objective if isinstance(request, PackAdvisorRequest) else str(request)
    objective = " ".join(objective.split())
    if not objective:
        raise ValueError("A pack objective is required")
    category, rules = _rules_for_objective(objective)
    recommendations: list[DocumentRecommendation] = []
    seen: set[str] = set()
    for rule in rules:
        if rule.document_type not in CURRENT_DOCUMENT_TYPES:
            raise ValueError(f"Unknown canonical document type: {rule.document_type}")
        if rule.document_type in seen:
            continue
        seen.add(rule.document_type)
        recommendations.append(
            DocumentRecommendation(
                document_type=rule.document_type,
                title=rule.title,
                reason=rule.reason,
                priority=rule.priority,
                missing_data=_missing_data(profile, rule),
            )
        )

    required = [item for item in recommendations if item.priority == "required"]
    missing_by_document = {
        item.document_type: list(item.missing_data) for item in recommendations if item.missing_data
    }
    overall_missing = list(
        dict.fromkeys(missing for item in recommendations for missing in item.missing_data)
    )
    ready_required = sum(not item.missing_data for item in required)
    return PackAdvisorResponse(
        objective=objective,
        objective_category=category,
        recommendations=recommendations,
        profile_validation={
            "valid": ready_required == len(required),
            "required_ready": ready_required,
            "required_total": len(required),
            "completeness_ratio": (round(ready_required / len(required), 4) if required else 1.0),
            "missing_by_document": missing_by_document,
            "overall_missing": overall_missing,
        },
        total_required=len(required),
        total_optional=len(recommendations) - len(required),
        can_generate_all=ready_required == len(required),
    )


def validate_profile_for_generation(
    profile: CompanyProfile, document_types: list[str]
) -> dict[str, object]:
    """Validate known recommended types without performing generation."""
    unique_types = list(dict.fromkeys(document_types))
    rules = {
        rule.document_type: rule
        for candidate in (
            *_banking_rules(True),
            *_rules_for_objective("board governance")[1],
            *_rules_for_objective("consulting agreement")[1],
            *_rules_for_objective("general information")[1],
        )
        for rule in (candidate,)
    }
    missing_by_document = {
        document_type: _missing_data(profile, rules[document_type])
        for document_type in unique_types
        if document_type in rules and _missing_data(profile, rules[document_type])
    }
    unknown_types = [
        document_type
        for document_type in unique_types
        if document_type not in CURRENT_DOCUMENT_TYPES
    ]
    overall_missing = list(
        dict.fromkeys(missing for values in missing_by_document.values() for missing in values)
    )
    return {
        "valid": not missing_by_document and not unknown_types,
        "missing_by_document": missing_by_document,
        "overall_missing": overall_missing,
        "unknown_document_types": unknown_types,
    }
