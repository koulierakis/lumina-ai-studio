"""Fact-safe smart field extraction for legacy deterministic document rendering."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .models import CompanyProfile

DEMO_COMPANY_NAMES = {"lumina corporate holdings", "acme corp", "example company"}


def _profile_dict(profile: CompanyProfile, field: str) -> dict[str, Any]:
    value = getattr(profile, field, None)
    return value if isinstance(value, dict) else {}


def _first_mapping(items: Any) -> dict[str, Any]:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return {}


def _placeholder(name: str) -> str:
    return f"[{name}]"


def extract_fact_safe_smart_fields(
    prompt: str, profile: CompanyProfile, title: str = ""
) -> dict[str, Any]:
    """Extract only supplied/profile facts; represent missing values as placeholders."""
    source = f"{title} {prompt}".strip()
    company_match = re.search(
        r"([A-ZΑ-Ω][A-ZΑ-Ω0-9&.,'’\- ]+\b(?:LLC|LTD|LIMITED|INC|CORP|SA|AG|LP|LLP|ΙΚΕ|ΑΕ|ΕΠΕ))",
        source,
        re.IGNORECASE,
    )
    person_match = re.search(
        r"(?:Managing Member|authorized signatory|appointing|represented by|by|διαχειριστ(?:ής|η)|εξουσιοδοτημέν(?:ος|η) υπογράφων):?\s*([A-ZΑ-ΩΆΈΉΊΌΎΏ][A-Za-zΑ-Ωα-ωΆ-ώ'’\-]+(?:\s+[A-ZΑ-ΩΆΈΉΊΌΎΏ][A-Za-zΑ-Ωα-ωΆ-ώ'’\-]+){1,4})",
        source,
        re.IGNORECASE,
    )
    jurisdiction_match = re.search(
        r"\b(Wyoming|Delaware|England and Wales|Cyprus|Greece|United States|United Kingdom|Switzerland|UAE|Singapore|Hong Kong|Ελλάδα|Κύπρος|Ηνωμένες Πολιτείες|Ηνωμένο Βασίλειο|Ελβετία)\b",
        source,
        re.IGNORECASE,
    )
    currency_match = re.search(r"(?<!\w)(EUR|USD|GBP|CHF|AED)(?!\w)|[€$£]", source, re.IGNORECASE)
    purpose_match = re.search(r"(?:Purpose|Σκοπός)\s*:\s*(.+?)(?:\n|$)", source, re.IGNORECASE)

    people = (
        getattr(profile, "authorized_signatories", [])
        or getattr(profile, "managers", [])
        or getattr(profile, "directors", [])
        or []
    )
    primary_person = _first_mapping(people)
    primary_bank = _first_mapping(getattr(profile, "bank_accounts", []) or [])
    legal_information = _profile_dict(profile, "legal_information")
    contact_information = _profile_dict(profile, "contact_information")
    addresses = getattr(profile, "addresses", []) or []

    profile_company = str(getattr(profile, "company_name", "") or "").strip()
    company_name = (
        company_match.group(1).strip(" ,.")
        if company_match
        else profile_company
        if profile_company and profile_company.casefold() not in DEMO_COMPANY_NAMES
        else _placeholder("COMPANY NAME")
    )

    explicit_person = person_match.group(1).strip() if person_match else ""
    profile_person = str(
        primary_person.get("full_name") or primary_person.get("name") or ""
    ).strip()
    person_name = explicit_person or profile_person or _placeholder("AUTHORIZED SIGNATORY")
    role = str(
        primary_person.get("role") or primary_person.get("authority") or ""
    ).strip() or _placeholder("AUTHORITY")

    bank_match = re.search(
        r"Bank of [A-ZΑ-Ω][A-Za-zΑ-Ωα-ωΆ-ώ ]+|for\s+[A-ZΑ-Ω][A-Za-zΑ-Ωα-ωΆ-ώ ]+Bank[A-Za-zΑ-Ωα-ωΆ-ώ ]*",
        source,
    )
    bank_text = (
        bank_match.group(0).replace("for ", "").strip()
        if bank_match
        else str(primary_bank.get("bank_name") or "").strip()
        or _placeholder("BANK")
    )

    date = datetime.now(UTC).date().isoformat()
    doc_number = f"LUMINA-{datetime.now(UTC).strftime('%Y%m%d')}-{abs(hash(source)) % 100000:05d}"
    jurisdiction = (
        jurisdiction_match.group(1)
        if jurisdiction_match
        else str(getattr(profile, "jurisdiction", "") or "").strip()
        or _placeholder("JURISDICTION")
    )
    registration_number = str(
        getattr(profile, "registration_number", "")
        or legal_information.get("registration")
        or legal_information.get("company_number")
        or ""
    ).strip() or _placeholder("REGISTRATION NUMBER")
    tax_number = str(
        getattr(profile, "ein_tax_number", "")
        or getattr(profile, "vat_number", "")
        or legal_information.get("tax_number")
        or ""
    ).strip() or _placeholder("TAX NUMBER")

    legal_form = str(getattr(profile, "legal_form", "") or "").strip()
    if not legal_form and company_match:
        legal_form = company_name.split()[-1]
    legal_form = legal_form or _placeholder("LEGAL FORM")

    registered_office = str(getattr(profile, "registered_office", "") or "").strip()
    if not registered_office and addresses:
        registered_office = str(addresses[0]).strip()
    registered_office = registered_office or _placeholder("REGISTERED OFFICE")

    address = str(getattr(profile, "principal_office", "") or "").strip()
    if not address and addresses:
        address = str(addresses[0]).strip()
    address = address or _placeholder("ADDRESS")

    if currency_match:
        currency = currency_match.group(1) or {"€": "EUR", "$": "USD", "£": "GBP"}.get(currency_match.group(0))
    else:
        currency = None

    return {
        "company_name": company_name,
        "trading_name": str(getattr(profile, "trading_name", "") or "").strip() or company_name,
        "legal_form": legal_form,
        "jurisdiction": jurisdiction,
        "registration_number": registration_number,
        "tax_number": tax_number,
        "managing_member": person_name.upper() if not person_name.startswith("[") else person_name,
        "authority": role,
        "directors": getattr(profile, "directors", []),
        "members": getattr(profile, "members", []),
        "shareholders": getattr(profile, "members", []),
        "authorized_signatory": person_name.upper() if not person_name.startswith("[") else person_name,
        "bank": bank_text,
        "bank_swift": str(primary_bank.get("swift") or "").strip() or _placeholder("SWIFT"),
        "bank_iban": str(primary_bank.get("iban") or "").strip() or _placeholder("IBAN"),
        "requested_purpose": purpose_match.group(1).strip() if purpose_match else _placeholder("PURPOSE"),
        "registered_office": registered_office,
        "date": date,
        "document_date": date,
        "effective_date": date,
        "reference_number": doc_number,
        "document_reference": doc_number,
        "document_number": doc_number,
        "currency": currency or _placeholder("CURRENCY"),
        "website": str(getattr(profile, "website", "") or contact_information.get("website") or "").strip() or _placeholder("WEBSITE"),
        "email": str(getattr(profile, "email", "") or contact_information.get("email") or "").strip() or _placeholder("EMAIL"),
        "phone": str(getattr(profile, "phone", "") or contact_information.get("phone") or "").strip() or _placeholder("PHONE"),
        "address": address,
        "company_number": registration_number,
    }
