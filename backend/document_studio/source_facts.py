"""Controlled extraction and verified application of source-derived corporate facts."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any

from .models import CompanyProfile, SourceCorporateFact, SourceFactConflict

PEOPLE_FIELDS = {
    "directors",
    "managers",
    "members",
    "beneficial_owners",
    "authorized_signatories",
}
SUPPORTED_FACT_FIELDS = {
    "company_name",
    "legal_form",
    "jurisdiction",
    "registration_number",
    "formation_date",
    "registered_office",
    "principal_office",
    *PEOPLE_FIELDS,
}
EXPLICIT_FACT_PATTERNS: tuple[tuple[str, str, float], ...] = (
    (
        "company_name",
        r"^(?:legal company name|legal name|company name|registered name)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.99,
    ),
    (
        "legal_form",
        r"^(?:legal form|legal status|entity type|company type)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.98,
    ),
    (
        "jurisdiction",
        r"^(?:jurisdiction|country of incorporation)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.98,
    ),
    (
        "registration_number",
        r"^(?:(?:company )?(?:registration|registry) (?:number|no\.?|#)|company number|reg\.? no\.?)\s*(?::|\||\t|\s{1,})\s*([A-Z]{1,6}[ .\-/]*\d[A-Z0-9 .\-/]*)$",
        0.99,
    ),
    (
        "formation_date",
        r"^(?:incorporation date|date of incorporation|date of registration|formed on|incorporated)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.98,
    ),
    (
        "registered_office",
        r"^(?:registered office|registered address)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.98,
    ),
    (
        "principal_office",
        r"^(?:principal office|principal address|business address|principal place of business)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.97,
    ),
    ("directors", r"^(?:director|directors)\s*(?::|\||\t|\s{2,})\s*(.+)$", 0.92),
    ("managers", r"^(?:manager|managers)\s*(?::|\||\t|\s{2,})\s*(.+)$", 0.90),
    ("members", r"^(?:member|members|shareholder|shareholders)\s*(?::|\||\t|\s{2,})\s*(.+)$", 0.90),
    (
        "beneficial_owners",
        r"^(?:ultimate beneficial owner|beneficial owner|beneficial owners|ubo|ubos)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.90,
    ),
    (
        "authorized_signatories",
        r"^(?:authorized signatory|authorized signatories)\s*(?::|\||\t|\s{2,})\s*(.+)$",
        0.92,
    ),
)


def _provenance_identity(entry: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(entry.get("field_name") or ""),
        json.dumps(entry.get("value"), ensure_ascii=False, sort_keys=True, default=str),
        str(entry.get("source_document_id") or ""),
        str(entry.get("source_document_name") or ""),
        str(entry.get("source_page_or_location") or ""),
        str(entry.get("extraction_method") or ""),
    )


def extract_source_corporate_facts(
    text: str,
    source_document_id: str,
    source_document_name: str,
    extraction_method: str = "deterministic_label_pattern",
) -> list[SourceCorporateFact]:
    """Extract only explicitly labeled facts from source text; never infer claims."""
    facts: list[SourceCorporateFact] = []
    seen: set[tuple[str, str]] = set()
    current_page: int | None = None
    page_line = 0

    for line_number, raw_line in enumerate((text or "").splitlines(), 1):
        line = raw_line.strip()
        page_marker = re.fullmatch(r"\[\[LUMINA_PAGE:(\d+)\]\]", line)
        if page_marker:
            current_page = int(page_marker.group(1))
            page_line = 0
            continue
        page_line += 1
        if not line:
            continue
        location = (
            f"page {current_page}, line {page_line}" if current_page else f"line {line_number}"
        )
        for field_name, pattern, confidence in EXPLICIT_FACT_PATTERNS:
            match = re.match(pattern, line, flags=re.IGNORECASE)
            if not match:
                continue
            value = re.sub(r"\s+", " ", match.group(1)).strip(" .;\t")
            identity = (field_name, _normalized_fact_value(field_name, value))
            if value and identity not in seen:
                seen.add(identity)
                facts.append(
                    SourceCorporateFact(
                        field_name=field_name,
                        value=value,
                        source_document_id=source_document_id,
                        source_document_name=source_document_name,
                        source_page_or_location=location,
                        extraction_method=extraction_method,
                        confidence=confidence,
                        verification_status=(
                            "VERIFIED"
                            if confidence >= 0.97 and field_name not in PEOPLE_FIELDS
                            else "CANDIDATE"
                        ),
                    )
                )
            break
    return facts


def _unicode_tokens(value: Any) -> str:
    """Normalize multilingual fact text without discarding non-Latin alphabets."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    chars = [character if character.isalnum() else " " for character in normalized]
    return " ".join("".join(chars).split())


def _normalized_fact_value(field_name: str, value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("full_name") or value
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if field_name == "registration_number":
        return "".join(character for character in text if character.isalnum())
    if field_name == "formation_date":
        for date_format in (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d.%m.%Y",
            "%d-%m-%Y",
            "%d %B %Y",
            "%d %b %Y",
        ):
            try:
                return datetime.strptime(text, date_format).date().isoformat()
            except ValueError:
                continue
    return _unicode_tokens(text)


def detect_source_fact_conflicts(
    facts: list[SourceCorporateFact], profile: CompanyProfile | None = None
) -> list[SourceFactConflict]:
    grouped: dict[str, dict[str, list[SourceCorporateFact]]] = {}
    for fact in facts:
        if fact.field_name not in SUPPORTED_FACT_FIELDS:
            continue
        normalized = _normalized_fact_value(fact.field_name, fact.value)
        if not normalized:
            continue
        grouped.setdefault(fact.field_name, {}).setdefault(normalized, []).append(fact)

    conflicts: list[SourceFactConflict] = []
    for field_name, values in grouped.items():
        current = getattr(profile, field_name, None) if profile else None
        source_conflict = field_name not in PEOPLE_FIELDS and len(values) > 1
        profile_conflict = (
            field_name not in PEOPLE_FIELDS
            and bool(current)
            and _normalized_fact_value(field_name, current) not in values
        )
        if source_conflict or profile_conflict:
            conflicts.append(
                SourceFactConflict(
                    field_name=field_name,
                    conflicting_values=[
                        {
                            "value": group[0].value,
                            "sources": [
                                {
                                    "document_id": item.source_document_id,
                                    "document_name": item.source_document_name,
                                    "location": item.source_page_or_location,
                                }
                                for item in group
                            ],
                        }
                        for group in values.values()
                    ],
                    current_company_profile_value=current,
                )
            )
    return conflicts


def apply_verified_source_facts(
    profile: CompanyProfile, facts: list[SourceCorporateFact]
) -> tuple[CompanyProfile, list[SourceFactConflict], list[str]]:
    """Apply supported VERIFIED facts without replacing conflicting profile data."""
    data = profile.model_dump()
    supported = [fact for fact in facts if fact.field_name in SUPPORTED_FACT_FIELDS]
    conflicts = detect_source_fact_conflicts(supported, profile)
    blocked = {item.field_name for item in conflicts}
    applied: list[str] = []
    provenance = {key: list(value) for key, value in profile.fact_provenance.items()}

    for fact in supported:
        if fact.verification_status != "VERIFIED" or fact.field_name in blocked:
            continue
        changed = False
        if fact.field_name in PEOPLE_FIELDS:
            existing = list(data.get(fact.field_name) or [])
            values = (
                [fact.value]
                if isinstance(fact.value, dict)
                else [
                    {"name": name, "full_name": name}
                    for name in re.split(r"\s*(?:;|,)\s*", str(fact.value))
                    if name.strip()
                ]
            )
            for value in values:
                person = dict(value)
                name = str(person.get("name") or person.get("full_name") or "").strip()
                if name and not any(
                    str(item.get("name") or item.get("full_name") or "").casefold()
                    == name.casefold()
                    for item in existing
                ):
                    existing.append({**person, "name": name, "full_name": name})
                    changed = True
            data[fact.field_name] = existing
        else:
            current = data.get(fact.field_name)
            if not current:
                data[fact.field_name] = fact.value
                changed = True

        entries = provenance.setdefault(fact.field_name, [])
        fact_provenance = fact.model_dump()
        identity = _provenance_identity(fact_provenance)
        if not any(_provenance_identity(entry) == identity for entry in entries):
            entries.append(fact_provenance)
            changed = True
        if changed and fact.field_name not in applied:
            applied.append(fact.field_name)

    data["fact_provenance"] = provenance
    return CompanyProfile.model_validate(data), conflicts, applied
