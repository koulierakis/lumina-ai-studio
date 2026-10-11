"""Greek acceptance contracts must be validated on their real content (Lumina integration regression)."""
from gold_builder.engine.semantic_acceptance import _tokens, validate_contract

REQUEST = "Δημιούργησε ελληνική εφαρμογή διαχείρισης πελατών με δημιουργία, αναζήτηση και μόνιμη αποθήκευση."
REQS = [
    {"id": "REQ-001", "kind": "functional", "text": "Ο χρήστης δημιουργεί νέο πελάτη με Ονοματεπώνυμο"},
    {"id": "REQ-002", "kind": "functional", "text": "Η αναζήτηση φιλτράρει τη λίστα πελατών"},
    {"id": "REQ-003", "kind": "functional", "text": "Οι πελάτες παραμένουν μόνιμα μετά από επαναφόρτωση"},
]
STEPS = [
    {"action": "open", "args": {"url": "/"}},
    {"action": "fill", "args": {"selector": "#customer-name", "value": "Γιώργος Παπαδόπουλος"}},
    {"action": "click", "args": {"selector": "#save-customer"}},
    {"action": "assert_text", "args": {"selector": "#customer-list", "contains": "Γιώργος Παπαδόπουλος"}, "requirement_id": "REQ-001"},
    {"action": "fill", "args": {"selector": "#search", "value": "Παπαδόπουλος"}},
    {"action": "assert_text", "args": {"selector": "#customer-list", "contains": "Παπαδόπουλος"}, "requirement_id": "REQ-002"},
    {"action": "reload", "args": {}},
    {"action": "assert_text", "args": {"selector": "#customer-list", "contains": "Γιώργος Παπαδόπουλος"}, "requirement_id": "REQ-003"},
]


def test_greek_text_tokenizes_accent_and_case_insensitively():
    assert _tokens("ΠΑΠΑΔΟΠΟΥΛΟΣ") == _tokens("Παπαδόπουλος") != set()


def test_greek_contract_with_real_value_evidence_is_accepted():
    ok, errors = validate_contract(STEPS, REQUEST, REQS)
    assert ok, errors


def test_greek_persistence_still_requires_assertion_after_reload():
    no_reload = [s for s in STEPS if s["action"] != "reload"]
    ok, errors = validate_contract(no_reload, REQUEST, REQS)
    assert not ok
    assert any("REQ-003" in e for e in errors)


def test_greek_requirement_with_unrelated_assertion_is_still_rejected():
    bogus = STEPS[:3] + [{"action": "assert_visible", "args": {"selector": "body"}, "requirement_id": "REQ-001"}]
    ok, errors = validate_contract(bogus, REQUEST, REQS[:1])
    assert not ok


def _real_contract():
    import json
    from pathlib import Path
    # Contract emitted by claude-sonnet-4-6 for the Greek CRM request and rejected by the unpatched validator.
    return json.loads((Path(__file__).parent / "fixtures" / "gold_builder_greek_crm_contract.json").read_text(encoding="utf-8"))


def test_real_llm_greek_contract_is_accepted_without_unprovable_requirement():
    data = _real_contract()
    reqs = [r for r in data["requirements"] if r["id"] != "REQ-007"]
    steps = [s for s in data["verification_scenario"] if s.get("requirement_id") != "REQ-007"]
    ok, errors = validate_contract(steps, REQUEST, reqs)
    assert ok, errors


def test_real_llm_greek_contract_still_rejects_unprovable_integration_requirement():
    data = _real_contract()
    ok, errors = validate_contract(data["verification_scenario"], REQUEST, data["requirements"])
    assert not ok
    assert all("REQ-007" in e for e in errors)


def test_second_real_llm_greek_contract_with_transliterated_selectors_is_accepted():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "fixtures" / "gold_builder_greek_crm_contract_2.json").read_text(encoding="utf-8"))
    ok, errors = validate_contract(data["verification_scenario"], REQUEST, data["requirements"])
    assert ok, errors


def test_transliterated_selector_shares_tokens_with_greek_text():
    assert {"lista"} <= _tokens("#lista-pelatwn") & _tokens("λίστα πελατών")
