from __future__ import annotations

from document_studio.models import CompanyProfile, SourceCorporateFact
from document_studio.source_facts import detect_source_fact_conflicts


def fact(field_name: str, value: str, source_id: str) -> SourceCorporateFact:
    return SourceCorporateFact(
        field_name=field_name,
        value=value,
        source_document_id=source_id,
        source_document_name=f"{source_id}.pdf",
        source_page_or_location="page 1, line 1",
        confidence=0.99,
        verification_status="VERIFIED",
    )


def test_greek_company_names_are_not_collapsed_to_empty_normalization():
    conflicts = detect_source_fact_conflicts(
        [
            fact("company_name", "ΑΛΦΑ ΕΜΠΟΡΙΚΗ Ι.Κ.Ε.", "source-a"),
            fact("company_name", "ΒΗΤΑ ΕΜΠΟΡΙΚΗ Ι.Κ.Ε.", "source-b"),
        ]
    )

    assert len(conflicts) == 1
    assert conflicts[0].field_name == "company_name"
    assert {entry["value"] for entry in conflicts[0].conflicting_values} == {
        "ΑΛΦΑ ΕΜΠΟΡΙΚΗ Ι.Κ.Ε.",
        "ΒΗΤΑ ΕΜΠΟΡΙΚΗ Ι.Κ.Ε.",
    }


def test_equivalent_greek_company_name_does_not_create_false_conflict():
    profile = CompanyProfile(company_name="Εμπορική Ελλάδος ΙΚΕ")

    conflicts = detect_source_fact_conflicts(
        [fact("company_name", "ΕΜΠΟΡΙΚΗ   ΕΛΛΑΔΟΣ ΙΚΕ", "source-a")],
        profile,
    )

    assert conflicts == []


def test_greek_registered_office_conflict_is_detected_against_profile():
    profile = CompanyProfile(registered_office="Ασκληπιού 10, Τρίκαλα")

    conflicts = detect_source_fact_conflicts(
        [fact("registered_office", "Καρανάσιου 20, Τρίκαλα", "source-a")],
        profile,
    )

    assert len(conflicts) == 1
    assert conflicts[0].field_name == "registered_office"


def test_european_dotted_formation_dates_compare_equally():
    profile = CompanyProfile(formation_date="05.08.2026")

    conflicts = detect_source_fact_conflicts(
        [fact("formation_date", "05/08/2026", "source-a")],
        profile,
    )

    assert conflicts == []
