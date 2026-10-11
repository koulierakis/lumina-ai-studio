"""Validation of semantic browser acceptance contracts.

The planner may describe a scenario, but only browser execution decides its
result. This prevents a smoke test from being mistaken for behavioural proof.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

MUTATIONS = {"click", "submit", "select", "check"}
ASSERTIONS = {"assert_visible", "assert_hidden", "assert_text", "assert_not_text",
              "assert_url", "assert_count", "assert_value", "assert_in_viewport", "assert_no_overflow"}
USER_ACTION_WORDS = r"(?:create|edit|update|delete|remove|cancel|book|search|filter|save|submit|upload|login|sign\s*in)"
USER_WORKFLOW = re.compile(
    rf"\b(?:user|users|visitor|visitors|customer|customers|client|clients|member|members|admin|staff|i|we)\b"
    rf".{{0,60}}\b{USER_ACTION_WORDS}\b",
    re.I,
)
DOMAIN_WORKFLOW = re.compile(
    rf"(?:\b{USER_ACTION_WORDS}\b.{{0,50}}\b(?:tasks?|contacts?|bookings?|reservations?|records?|items?|profiles?|payments?)\b|"
    rf"\b(?:tasks?|contacts?|bookings?|reservations?|records?|items?|profiles?|payments?)\b.{{0,50}}\b{USER_ACTION_WORDS}\b)",
    re.I,
)
INTERACTIVE_PRODUCT = re.compile(
    r"\b(task manager|todo(?: list)?|crm|booking(?: system| app)?|reservation(?: system| app)?|"
    r"checkout|authentication|login form|contact form|search interface|filter(?:ing)? interface)\b",
    re.I,
)
PERSISTENCE_WORDS = re.compile(
    r"\b(persist(?:s|ed|ent|ence)?|reload|saved|storage)\b|μόνιμ|μονιμ|επαναφόρτωσ|επαναφορτωσ|διατηρ",
    re.I,
)
RESPONSIVE_WORDS = re.compile(r"\b(mobile|responsive|phone|tablet|small screen|desktop)\b", re.I)

# Greek is written with tonos (ά, έ, ή...). Users often type instructions in
# UPPERCASE, where the tonos is dropped ("ΕΛΕΓΞΕ", "ΜΗΝ ΑΛΛΑΞΕΙΣ") or kept
# inconsistently. Matching on the raw text then misses the intent and a real
# read-only audit is treated as a mutating job. Folding accents and case before
# matching makes every spelling variant hit the same pattern.
_ACCENT_FOLD = str.maketrans(
    "ΆΈΉΊΌΎΏάέήίόύώϊϋΐΰΪΫ",
    "ΑΕΗΙΟΥΩαεηιουωιυιυΙΥ",
)


def normalize_greek(text: str) -> str:
    """Lowercase and strip accents so Greek is matched independent of casing.

    `str.lower()` keeps the tonos ("Έ".lower() == "έ"), so both accents and case
    are removed explicitly.
    """
    folded = unicodedata.normalize("NFD", text or "")
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return stripped.translate(_ACCENT_FOLD).lower()


# Read-only / audit intent. A request that explicitly asks to inspect/analyse a
# repository or module AND explicitly forbids modification is a read-only audit:
# it has no user-facing behaviour to prove in a browser, so the mutation,
# persistence and responsive clauses of the acceptance contract do not apply.
_READ_ONLY_ACTION = re.compile(
    r"\b(audit|inspect|analyse|analyze|review|explain|inventory|report|"
    r"assess|evaluate|document|diagnose|summari[sz]e|map)\b",
    re.I,
)
_GREEK_READ_ONLY_ACTION = re.compile(
    r"(ελεγξ\w*|ελεγχ\w*|αξιολογησ\w*|αναλυσ\w*|αναφορα\w*|καταγραφ\w*|"
    r"επιθεωρησ\w*|εξηγησ\w*|τεκμηριωσ\w*|διαγνωσ\w*|χαρτογραφησ\w*|"
    r"αποτιμησ\w*|περιγραφ\w*|εντοπισ\w*|εποπτευσ\w*)",
    re.I,
)
# Explicit prohibitions on modifying the repository. The Greek negation "μην"
# (uppercased "ΜΗΝ" in real audit prompts) is covered too.
_NO_MODIFY = re.compile(
    r"(do\s+not\s+(modify|change|edit|touch|alter|write)|"
    r"don'?t\s+(modify|change|edit|touch|alter|write)|"
    r"no\s+(code\s+)?(changes?|modifications?|edits?)|"
    r"without\s+(modifying|changing|editing)|"
    r"read[-\s]?only|audit\s+only|"
    r"μην\s+(αλλαξ\w*|τροποποιησ\w*|καν\w*|υλοποιησ\w*|δημιουργησ\w*|"
    r"ανοιξ\w*|πειραξ\w*|αγγιξ\w*|ακουμπησ\w*|σβησ\w*|διαγραψ\w*)|"
    r"χωρις\s+(αλλαγ\w*|τροποποιησ\w*|μεταβολ\w*))",
    re.I,
)
# A leading implementation directive overrides read-only intent: a "FIX MODE"
# job that merely *describes* read-only semantics is still a mutating job. Only
# a directive that is not itself negated ("do not modify", "ΜΗΝ αλλάξεις") counts.
_MUTATION_DIRECTIVE = re.compile(
    r"\b(add|create|implement|build|fix|repair|change|modify|edit|update|remove|"
    r"delete|refactor|rename|migrate|upgrade|install|introduce|write|patch|"
    r"apply|deploy|enable|disable|improve|enhance|optimize|extend|support|"
    r"generate|commit|push)\b",
    re.I,
)
_GREEK_MUTATION_DIRECTIVE = re.compile(
    r"\b(διορθωσ\w*|βελτιωσ\w*|προσθεσ\w*|υλοποιησ\w*|φτιαξ\w*|αλλαξ\w*|"
    r"καν(?:ω|εις|ει|ουμε|ετε|ουν|ουνε|ε|τε|αμε|ατε|οντας)|"
    r"ενημερωσ\w*|αφαιρεσ\w*|διαγραψ\w*|σβησ\w*|μετατρεψ\w*|αναβαθμισ\w*|"
    r"εγκαταστησ\w*|δημιουργησ\w*|επισκευασ\w*)\b",
    re.I,
)
# Nouns naming a real edit, used to tell the light verb apart: "κάνε αλλαγές"
# is a mutation while "κάνε έλεγχο" is an audit.
_GREEK_EDIT_OBJECT = re.compile(
    r"(αλλαγ\w*|τροποποιησ\w*|διορθωσ\w*|προσθεσ\w*|ενημερωσ\w*|βελτιωσ\w*|"
    r"μετατροπ\w*|αναβαθμισ\w*|εγκαταστασ\w*|επισκευ\w*|δημιουργ\w*|"
    r"αφαιρεσ\w*|διαγραφ\w*|σβησ\w*|υλοποιησ\w*|φτιαξ\w*)",
    re.I,
)
_NEGATOR = re.compile(
    r"(do\s+not|don'?t|must\s+not|never|without|avoid|"
    r"μην|μη\s|όχι|οχι|χωρίς|χωρις)",
    re.I,
)
# A negator only negates a verb inside its own clause, so a prohibition
# ("ΜΗΝ ΑΛΛΑΞΕΙΣ.") must not suppress a later directive ("ΔΙΟΡΘΩΣΕ").
_CLAUSE_BOUNDARY = re.compile(r"[.;!?\n,·]")
_READ_ONLY_DIRECTIVE_CHARS = 160


def _is_negated(text: str, verb_start: int, window: int = 24) -> bool:
    segment = text[max(0, verb_start - window):verb_start]
    cut = 0
    for boundary in _CLAUSE_BOUNDARY.finditer(segment):
        cut = boundary.end()
    return bool(_NEGATOR.search(segment[cut:]))


def _light_verb_object(text: str, start: int, limit: int = 60) -> str:
    """The object phrase of "κάνε", ending at the next clause or prohibition."""
    chunk = text[start:start + limit]
    stop = len(chunk)
    for pattern in (_CLAUSE_BOUNDARY, _NEGATOR):
        for match in pattern.finditer(chunk):
            stop = min(stop, match.start())
    return chunk[:stop]


def _has_positive_mutation_directive(text: str) -> bool:
    """A mutation verb that is not itself negated in the leading directive."""
    for pattern in (_MUTATION_DIRECTIVE, _GREEK_MUTATION_DIRECTIVE):
        for match in pattern.finditer(text):
            if _is_negated(text, match.start()):
                continue
            # "κάνε" is a light verb: "κάνε έλεγχο" is an audit, not an edit. Only
            # treat it as a mutation directive when its object is not a read-only
            # action ("κάνε έλεγχο" vs "κάνε αλλαγές").
            if match.group(0).startswith("καν"):
                obj = _light_verb_object(text, match.end())
                if _GREEK_READ_ONLY_ACTION.search(obj) and not _GREEK_EDIT_OBJECT.search(obj):
                    continue
            return True
    return False


def read_only_request(request: str) -> bool:
    """True when the request is an explicit read-only inspection/audit.

    Requires BOTH a read-only action verb (audit/inspect/analyse/report...) and
    an explicit prohibition on modification. A leading implementation directive
    ("FIX MODE", "Implement...") overrides that, so an implementation job that
    merely *describes* read-only semantics is still treated as mutating.

    Text is accent- and case-folded first so "ΕΛΕΓΞΕ ... ΜΗΝ ΑΛΛΑΞΕΙΣ" matches
    just like "έλεγξε ... μην αλλάξεις".
    """
    text = normalize_greek(request)
    if not (_READ_ONLY_ACTION.search(text) or _GREEK_READ_ONLY_ACTION.search(text)):
        return False
    if not _NO_MODIFY.search(text):
        return False
    return not _has_positive_mutation_directive(text[:_READ_ONLY_DIRECTIVE_CHARS])


def semantic_verification_applies(request: str) -> bool:
    text = request or ""
    if read_only_request(text):
        return False
    # Distinguish developer-edit wording ("add a footer line", "modify CSS")
    # from behaviour the end user must perform in the finished application.
    # Generic edit verbs alone must not force a synthetic browser mutation.
    return bool(
        PERSISTENCE_WORDS.search(text)
        or USER_WORKFLOW.search(text)
        or DOMAIN_WORKFLOW.search(text)
        or INTERACTIVE_PRODUCT.search(text)
    )


def contract_verification_applies(request: str, requirements: Iterable[Any] = ()) -> bool:
    if read_only_request(request):
        return False
    if semantic_verification_applies(request) or bool(RESPONSIVE_WORDS.search(request or "")):
        return True
    return any(bool(getattr(r, "verifiable", r.get("verifiable", True) if isinstance(r, dict) else True)) for r in requirements or [])


def validate_contract(
    scenario: Iterable[Dict[str, Any]],
    request: str,
    requirements: Iterable[Any] = (),
) -> Tuple[bool, List[str]]:
    """Reject contracts that cannot prove requested observable outcomes."""
    raw_steps = list(scenario or [])
    if not contract_verification_applies(request, requirements):
        return True, []
    actions = [str(s.get("action", "")).lower() for s in raw_steps]
    errors: List[str] = []
    if semantic_verification_applies(request) and not any(a in MUTATIONS or a == "fill" for a in actions):
        errors.append("semantic contract has no user mutation")
    meaningful_assertions = []
    for i, (action, step) in enumerate(zip(actions, raw_steps)):
        args = step.get("args") or step
        selector = str(args.get("selector", ""))
        has_expectation = any(k in args for k in ("contains", "equals", "at_least"))
        if action in ASSERTIONS and (has_expectation or selector not in ("", "body")):
            meaningful_assertions.append(i)
    if semantic_verification_applies(request) and not meaningful_assertions:
        errors.append("semantic contract has no observable outcome assertion")
    mutations = [i for i, a in enumerate(actions) if a in MUTATIONS]
    assertions = meaningful_assertions
    if semantic_verification_applies(request) and mutations and not any(i > mutations[0] for i in assertions):
        errors.append("semantic contract does not assert state after mutation")
    if PERSISTENCE_WORDS.search(request or ""):
        if "reload" not in actions:
            errors.append("persistence requirement has no reload step")
        elif not any(i > actions.index("reload") for i in assertions):
            errors.append("persistence requirement is not asserted after reload")

    if RESPONSIVE_WORDS.search(request or ""):
        widths = []
        overflow_checks = 0
        for step in raw_steps:
            action = str(step.get("action", "")).lower()
            args = step.get("args") or step
            if action == "set_viewport":
                try:
                    widths.append(int(args.get("width")))
                except (TypeError, ValueError):
                    pass
            elif action == "assert_no_overflow":
                overflow_checks += 1
        responsive_text = " ".join(
            [request or ""]
            + [
                str(r.get("text", "")) if isinstance(r, dict) else str(getattr(r, "text", ""))
                for r in requirements or []
            ]
        )
        mentions_mobile = bool(re.search(r"mobile|phone|small\s*screen|tablet", responsive_text, re.I))
        mentions_desktop = bool(re.search(r"desktop|wide\s*screen", responsive_text, re.I))
        needs_both = mentions_mobile and mentions_desktop
        # A mobile-only requirement must not be satisfied by a desktop-only
        # scenario, and vice versa.
        if mentions_mobile or not mentions_desktop:
            if not any(w <= 480 for w in widths):
                errors.append("responsive requirement has no mobile viewport verification")
        if mentions_desktop or not mentions_mobile:
            if not any(w >= 1024 for w in widths):
                errors.append("responsive requirement has no desktop viewport verification")
        required_overflow = 2 if needs_both else 1
        if overflow_checks < required_overflow:
            if needs_both:
                errors.append("responsive requirement needs overflow checks on desktop and mobile")
            else:
                errors.append("responsive requirement needs an overflow check")

    verifiable_ids = set()
    req_meta: Dict[str, Tuple[str, str]] = {}
    for requirement in requirements or []:
        if isinstance(requirement, dict):
            req_id = str(requirement.get("id", "")).strip()
            kind = str(requirement.get("kind", "")).lower()
            text = str(requirement.get("text", ""))
            verifiable = bool(requirement.get("verifiable", True))
        else:
            req_id = str(getattr(requirement, "id", "")).strip()
            kind = str(getattr(requirement, "kind", "")).lower()
            text = str(getattr(requirement, "text", ""))
            verifiable = bool(getattr(requirement, "verifiable", True))
        if req_id and verifiable:
            verifiable_ids.add(req_id)
            req_meta[req_id] = (kind, text)

    if verifiable_ids:
        covered = set()
        linked = set()
        for i, (action, step) in enumerate(zip(actions, raw_steps)):
            if action not in ASSERTIONS and action != "assert_no_overflow":
                continue
            req_id = _step_requirement_id(step)
            if not req_id or req_id not in req_meta:
                continue
            linked.add(req_id)
            kind, text = req_meta[req_id]
            # A requirement_id is accepted only when the assertion it names is
            # genuine semantic evidence for that requirement — regardless of who
            # wrote the link (the LLM or the deterministic fallback). This blocks
            # a semantically wrong LLM mapping from passing coverage validation.
            if _evidence_ok(req_id, kind, text, raw_steps, i):
                covered.add(req_id)
        # A requirement is inconsistent only when it is linked to assertions but
        # NONE of them is genuine evidence. A supplementary non-evidence link
        # (e.g. an existence check alongside the exact-text assertion that
        # actually proves the requirement) must not invalidate a requirement that
        # IS proven by another of its own assertions.
        inconsistent = linked - covered
        if inconsistent:
            errors.append(
                "verification contract links a requirement to an assertion that "
                "does not prove it: " + ", ".join(sorted(inconsistent))
            )
        missing = sorted(verifiable_ids - covered)
        if missing:
            errors.append("verification contract does not cover requirements: " + ", ".join(missing))
    return not errors, errors


def repair_contract_coverage(
    scenario: Iterable[Dict[str, Any]],
    request: str,
    requirements: Iterable[Any] = (),
) -> List[Dict[str, Any]]:
    """Repair only coverage links that can be inferred without weakening acceptance."""
    steps = [dict(step) for step in (scenario or [])]
    reqs = list(requirements or [])

    def req_fields(req):
        if isinstance(req, dict):
            return str(req.get("id", "")).strip(), str(req.get("kind", "")).lower(), str(req.get("text", ""))
        return str(getattr(req, "id", "")).strip(), str(getattr(req, "kind", "")).lower(), str(getattr(req, "text", ""))

    covered = set()
    for step in steps:
        action = str(step.get("action", "")).lower()
        if action in ASSERTIONS or action == "assert_no_overflow":
            req_id = str(step.get("requirement_id") or (step.get("args") or {}).get("requirement_id") or "").strip()
            if req_id:
                covered.add(req_id)

    # Responsive requirements have deterministic proof: overflow assertions at
    # desktop/mobile viewports. Attach the requirement id to those real checks.
    for req in reqs:
        req_id, kind, text = req_fields(req)
        if not req_id or req_id in covered:
            continue
        if kind == "responsive" or RESPONSIVE_WORDS.search(text or ""):
            for step in steps:
                if str(step.get("action", "")).lower() == "assert_no_overflow" and not step.get("requirement_id"):
                    step["requirement_id"] = req_id
            covered.add(req_id)

    # Persistence can be linked only to a real assertion after reload that
    # actually observes the persisted state. An assertion with no expected value
    # (e.g. a generic element is visible) is not proof of persistence.
    actions = [str(step.get("action", "")).lower() for step in steps]
    if "reload" in actions:
        reload_index = actions.index("reload")
        for req in reqs:
            req_id, _kind, text = req_fields(req)
            if not req_id or req_id in covered or not PERSISTENCE_WORDS.search(text or ""):
                continue
            for i in range(reload_index + 1, len(steps)):
                action = str(steps[i].get("action", "")).lower()
                if action in ASSERTIONS and not steps[i].get("requirement_id") and _has_expectation(steps[i]):
                    steps[i]["requirement_id"] = req_id
                    covered.add(req_id)
                    break
    return steps


_WORD = re.compile(r"[^\W_]+")  # letters/digits in any script (Greek requirements must tokenize)
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "be", "can", "user", "users", "i", "we", "should", "must", "will",
    "that", "this", "it", "as", "at", "by", "from", "app", "application",
    "page", "site", "when", "then", "its",
}
# Words too generic to be, on their own, evidence that an assertion proves a
# requirement. A shared "note"/"task"/"item" is not proof of a specific verb.
_GENERIC_TOKENS = {
    "note", "task", "item", "text", "value", "result", "data", "content",
    "element", "button", "input", "form", "list", "name", "test", "field",
    "label", "title", "click", "visible", "hidden", "note",
}
# Selectors that address the whole document/root; an assertion on one of these
# with no expected value proves nothing specific.
_GENERIC_SELECTORS = {"", "body", "html", "head", "main", "*", "#app", "#root"}


def _stem(word: str) -> str:
    for suffix in ("ing", "ies", "ied", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


# Selectors commonly use camelCase identifiers ("#assistantStatus") while the
# requirement text spells the same concept in kebab/space case ("assistant
# status line"). Without splitting camelCase the two never share a token, so a
# genuine status-line assertion is rejected as non-evidence. Split only the
# identifier word boundaries (lower->Upper, acronym->Word) so digits/URLs stay
# intact.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


_GREEK_TO_LATIN = str.maketrans({
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th",
    "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p",
    "ρ": "r", "σ": "s", "τ": "t", "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
})


def _tokenize(text: Any) -> set:
    words: List[str] = []
    for chunk in _WORD.findall(str(text or "")):
        # Split camelCase BEFORE lowercasing; lowercasing first erases the
        # upper/lower boundary the split relies on.
        words.extend(w for w in _CAMEL_BOUNDARY.split(chunk) if w)
    tokens = set()
    for word in words:
        if len(word) < 3 or word.lower() in _STOPWORDS:
            continue
        folded = normalize_greek(word).replace("ς", "σ")
        tokens.add(_stem(folded))
        latin = folded.translate(_GREEK_TO_LATIN)
        if latin != folded:
            # LLM selectors transliterate Greek ("#lista-pelatwn"); match across scripts.
            tokens.add(_stem(latin))
    return tokens


def _tokens(text: Any) -> set:
    return _tokenize(text)


def _requirement_fields(req: Any) -> Tuple[str, str, str, bool]:
    if isinstance(req, dict):
        return (
            str(req.get("id", "")).strip(),
            str(req.get("kind", "")).lower(),
            str(req.get("text", "")),
            bool(req.get("verifiable", True)),
        )
    return (
        str(getattr(req, "id", "")).strip(),
        str(getattr(req, "kind", "")).lower(),
        str(getattr(req, "text", "")),
        bool(getattr(req, "verifiable", True)),
    )


def _step_requirement_id(step: Dict[str, Any]) -> str:
    return str(
        step.get("requirement_id")
        or (step.get("args") or {}).get("requirement_id")
        or ""
    ).strip()


def _is_assertion_action(action: str) -> bool:
    return action in ASSERTIONS or action == "assert_no_overflow"


def _has_expectation(step: Dict[str, Any]) -> bool:
    args = step.get("args") or step
    for key in ("contains", "equals", "at_least"):
        if key not in args:
            continue
        value = args[key]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            # An empty/generic expected value proves nothing.
            continue
        return True
    return False


def _is_meaningful_assertion(step: Dict[str, Any]) -> bool:
    action = str(step.get("action", "")).lower()
    if not _is_assertion_action(action):
        return False
    args = step.get("args") or step
    selector = str(args.get("selector", ""))
    # A generic container/body assertion with no expected value proves nothing
    # about a specific requirement.
    if selector in _GENERIC_SELECTORS and not _has_expectation(step):
        return False
    return _has_expectation(step) or selector not in ("", "body")


def _context_parts(steps: List[Dict[str, Any]], index: int, *, include_preceding_selectors: bool) -> List[str]:
    step = steps[index]
    args = step.get("args") or step
    parts = [str(args.get("selector", "")), str(step.get("action", ""))]
    for key in ("contains", "equals", "at_least", "value"):
        if key in args:
            parts.append(str(args[key]))
    j = index - 1
    while j >= 0 and not _is_assertion_action(str(steps[j].get("action", "")).lower()):
        prev = steps[j].get("args") or steps[j]
        if "value" in prev:
            parts.append(str(prev["value"]))
        if include_preceding_selectors and prev.get("selector"):
            parts.append(str(prev["selector"]))
        j -= 1
    return parts


def _assertion_context(steps: List[Dict[str, Any]], index: int, *, include_preceding_selectors: bool = False) -> set:
    return _tokens(" ".join(_context_parts(steps, index, include_preceding_selectors=include_preceding_selectors)))


def _expected_values(step: Dict[str, Any]) -> set:
    args = step.get("args") or step
    return _tokens(" ".join(str(args[k]) for k in ("contains", "equals", "at_least") if k in args))


def _workflow_typed_values(steps: List[Dict[str, Any]], index: int) -> set:
    values: set = set()
    j = index - 1
    # A run of consecutive assertions all observe the same preceding workflow.
    while j >= 0 and _is_assertion_action(str(steps[j].get("action", "")).lower()):
        j -= 1
    while j >= 0 and not _is_assertion_action(str(steps[j].get("action", "")).lower()):
        prev = steps[j].get("args") or steps[j]
        if "value" in prev:
            values |= _tokens(str(prev["value"]))
        j -= 1
    return values


def _typed_values_before(steps: List[Dict[str, Any]], end: int) -> set:
    values: set = set()
    for prev in steps[:end]:
        prev_args = prev.get("args") or prev
        if "value" in prev_args:
            values |= _tokens(str(prev_args["value"]))
    return values


def _expected_raw(step: Dict[str, Any]) -> str:
    args = step.get("args") or step
    return " ".join(str(args[k]) for k in ("contains", "equals") if k in args)


_DISPLAY_KINDS = {"ui", "data"}
_GREEK_UI_REQUIREMENT = re.compile(r"ελληνικ|\bgreek\b")
_GREEK_CHARS = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")



def _text_has(text: str, pattern) -> bool:
    return bool(pattern.search(text or ""))


def _is_mobile_context(text: str) -> bool:
    return bool(re.search(r"mobile|phone|small\s*screen|tablet|390|375|360|414|320", text, re.I))


def _is_desktop_context(text: str) -> bool:
    return bool(re.search(r"desktop|1440|1280|1920|1024|wide", text, re.I))


# Verbs that mean "the subject is destroyed/removed". A delete requirement can
# only be proven by an assertion that observes the subject's absence.
_REMOVAL_WORDS = {"delete", "remove", "cancel", "clear", "discard"}
# Verbs that mean "the subject is created/present". Proving creation with an
# absence assertion is a false negative/positive mismatch.
_PRESENCE_WORDS = {"create", "add", "insert", "register", "upload", "submit"}
# Assertions whose semantics are "must NOT be present".
_NEGATIVE_ACTIONS = {"assert_hidden", "assert_not_text"}


def _action_compatible(req_text: str, step: Dict[str, Any]) -> bool:
    """Behaviour-verb compatibility between a requirement and an assertion.

    A delete/remove requirement cannot be proven by a positive visibility/text
    assertion, and a create/presence requirement cannot be proven by a negative
    (absence) assertion. This blocks cross-mapping unrelated requirements that
    merely share a noun such as "note".
    """
    action = str(step.get("action", "")).lower()
    req_tokens = _tokens(req_text)
    wants_removal = bool(req_tokens & _REMOVAL_WORDS)
    wants_presence = bool(req_tokens & _PRESENCE_WORDS)
    if wants_removal and not wants_presence:
        return action in _NEGATIVE_ACTIONS
    if wants_presence and not wants_removal:
        return action not in _NEGATIVE_ACTIONS
    return True


def _selector_tokens(step: Dict[str, Any]) -> set:
    args = step.get("args") or step
    return _tokens(str(args.get("selector", "")))


_NON_INTERACTION_ACTIONS = {
    "open", "goto", "navigate", "reload", "wait", "wait_for", "set_viewport",
    "screenshot", "close", "scroll", "assert_no_overflow",
}


def _selector_interacted(steps: List[Dict[str, Any]], index: int, step: Dict[str, Any]) -> bool:
    """True when an earlier action actually interacted with the asserted element.

    Distinguishes a real behavioural proof ("click #delete" then assert) from a
    static "some element happens to be visible" assertion.
    """
    target = _selector_tokens(step)
    if not target:
        return False
    for j in range(index):
        prev = steps[j]
        prev_action = str(prev.get("action", "")).lower()
        if _is_assertion_action(prev_action) or prev_action in _NON_INTERACTION_ACTIONS:
            continue
        if _selector_tokens(prev) & target:
            return True
    return False


def _nearest_viewport_width(steps: List[Dict[str, Any]], index: int) -> Optional[int]:
    for j in range(index - 1, -1, -1):
        step = steps[j]
        if str(step.get("action", "")).lower() != "set_viewport":
            continue
        args = step.get("args") or step
        try:
            return int(args.get("width"))
        except (TypeError, ValueError):
            return None
    return None


def _responsive_evidence_ok(text: str, steps: List[Dict[str, Any]], index: int) -> bool:
    """Deterministic proof for a responsive/overflow requirement.

    An overflow check proves a responsive requirement only at a viewport the
    requirement actually asks about: a mobile-only requirement is not proven by
    a desktop check, and vice versa.
    """
    step = steps[index]
    action = str(step.get("action", "")).lower()
    if action != "assert_no_overflow":
        context_text = " ".join(_context_parts(steps, index, include_preceding_selectors=True))
        return _text_has(context_text, re.compile(r"overflow", re.I)) and _is_mobile_context(context_text)
    width = _nearest_viewport_width(steps, index)
    req_lower = (text or "").lower()
    mentions_mobile = bool(re.search(r"mobile|phone|small\s*screen|tablet", req_lower))
    mentions_desktop = bool(re.search(r"desktop|wide\s*screen", req_lower))
    if mentions_mobile and not mentions_desktop:
        return width is not None and width <= 480
    if mentions_desktop and not mentions_mobile:
        return width is not None and width >= 1024
    # Generic responsive requirement: an overflow check at a real viewport counts.
    return width is not None


def _evidence_ok(req_id: str, kind: str, text: str, steps: List[Dict[str, Any]], index: int) -> bool:
    """True only when the assertion is genuine evidence for the requirement.

    Evidence is one of:
      * a significant (non-generic, >=4 char) token shared with the assertion
        context (selector / action / expected value / typed workflow value);
      * for a removal/presence requirement, a polarity-compatible assertion that
        shares the object noun and follows a matching workflow action;
      * an assertion whose expected value is a value typed earlier in the flow
        (the canonical create/persist proof);
      * a responsive requirement proven by a mobile-context overflow check.

    Persistence requirements additionally require the assertion to occur after a
    reload step.
    """
    step = steps[index]
    if not _action_compatible(text, step):
        return False

    req_tokens = _tokens(text)
    is_removal = bool(req_tokens & _REMOVAL_WORDS) and not bool(req_tokens & _PRESENCE_WORDS)
    is_presence = bool(req_tokens & _PRESENCE_WORDS) and not bool(req_tokens & _REMOVAL_WORDS)

    # For a removal requirement the only genuine proof is that the *object* is
    # absent. An absence assertion on the action control itself (a selector that
    # names the action verb, e.g. "#delete-note-btn") is not evidence the object
    # was removed, however many nouns it also happens to contain.
    if is_removal and (_selector_tokens(step) & (_REMOVAL_WORDS | _PRESENCE_WORDS)):
        return False

    # Persistence is only ever proven by an assertion after a reload.
    if _text_has(text, PERSISTENCE_WORDS):
        actions = [str(s.get("action", "")).lower() for s in steps]
        if "reload" not in actions:
            return False
        if index <= actions.index("reload"):
            return False

    context_tokens = _assertion_context(
        steps, index, include_preceding_selectors=is_removal or is_presence
    )
    overlap = req_tokens & context_tokens
    significant = {t for t in overlap if len(t) >= 4 and t not in _GENERIC_TOKENS}
    if significant:
        if kind != "behavior":
            return True
        # For a behaviour requirement a selector-noun collision alone is not
        # proof: the flow must have actually interacted with that element, or an
        # expected value must be observed (handled below). Otherwise a static
        # "element is visible" assertion could falsely verify an action.
        if _selector_interacted(steps, index, step):
            return True

    # Value linkage: the assertion expects a value that was typed earlier in the
    # workflow (create/edit/persist proof), or the expected value appears in the
    # requirement itself.
    expected = _expected_values(step)
    if expected:
        if expected & _workflow_typed_values(steps, index):
            return True
        if {t for t in (expected & req_tokens) if t not in _GENERIC_TOKENS}:
            return True
        # Persistence proof: a value typed before the reload is observed after it.
        if _text_has(text, PERSISTENCE_WORDS):
            reload_at = [str(s.get("action", "")).lower() for s in steps].index("reload")
            if {t for t in (expected & _typed_values_before(steps, reload_at)) if t not in _GENERIC_TOKENS}:
                return True
        # Display/data requirements (not behaviours) are proven by observing a value the
        # flow itself typed earlier, even across intermediate assertions.
        if kind in _DISPLAY_KINDS and {t for t in (expected & _typed_values_before(steps, index)) if t not in _GENERIC_TOKENS}:
            return True
        # "UI in Greek": an assertion that observes concrete Greek text is direct evidence.
        if _GREEK_UI_REQUIREMENT.search(normalize_greek(text)) and _GREEK_CHARS.search(_expected_raw(step)):
            return True

    # A removal requirement is proven by a polarity-compatible absence assertion
    # on the *object*, even when the only shared token is the generic object noun
    # (e.g. "delete a note" -> "#note is hidden"). If the asserted element is the
    # action control itself ("#delete-note-btn" hidden), that is not proof the
    # object was removed, so reject selectors that name the action verb.
    if is_removal and overlap:
        selector_tokens = _selector_tokens(step)
        if not (selector_tokens & (_REMOVAL_WORDS | _PRESENCE_WORDS)):
            return True
    # A presence requirement is weaker: the object merely existing does not prove
    # the action happened, so it needs the significant/value evidence above.

    # Responsive requirements have deterministic evidence: viewport + overflow.
    if kind == "responsive" or _text_has(text, RESPONSIVE_WORDS):
        return _responsive_evidence_ok(text, steps, index)
    return False


def ensure_requirement_coverage(
    scenario: Iterable[Dict[str, Any]],
    request: str,
    requirements: Iterable[Any] = (),
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Deterministically link uncovered requirements to existing real assertions.

    Used only after LLM-based semantic recovery has failed. It never invents
    selectors or expected values and never marks a requirement unverifiable, so
    strict validation is preserved: a requirement is covered only when the
    scenario already contains an assertion that observably proves it.

    A requirement is linked only when there is *genuine* semantic evidence:
    behaviour-verb compatibility (a delete requirement needs an absence
    assertion), a significant token overlap with the assertion context, or a
    responsive/overflow assertion in a matching mobile context. A bare 1:1
    "one requirement + one assertion" shape is never accepted on its own.

    Returns ``(steps, unresolved_ids)`` so the caller can still fail loudly when
    there is not enough deterministic evidence.
    """
    steps = [dict(step) for step in (scenario or [])]
    reqs = list(requirements or [])
    # Reuse the deterministic responsive/persistence linking first.
    steps = repair_contract_coverage(steps, request, reqs)

    assertion_indices = [
        i for i, step in enumerate(steps)
        if _is_meaningful_assertion(step)
        and str(step.get("action", "")).lower() != "assert_no_overflow"
    ]

    assigned: Dict[str, int] = {}
    for i in assertion_indices:
        req_id = _step_requirement_id(steps[i])
        if req_id:
            assigned[req_id] = i

    verifiable = [
        (req_id, kind, text)
        for req_id, kind, text, verifiable in (_requirement_fields(r) for r in reqs)
        if req_id and verifiable
    ]

    candidates: List[Tuple[int, str, int]] = []
    for req_id, kind, text in verifiable:
        if req_id in assigned:
            continue
        for i in assertion_indices:
            if i in assigned.values():
                continue
            if not _evidence_ok(req_id, kind, text, steps, i):
                continue
            req_tokens = _tokens(text) | _tokens(kind)
            score = len(req_tokens & _assertion_context(steps, i))
            candidates.append((score, req_id, i))

    # Deterministic greedy assignment: strongest evidence first, then stable
    # tie-breaks. An assertion is consumed once it is linked.
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    for _score, req_id, index in candidates:
        if req_id in assigned or index in assigned.values():
            continue
        steps[index]["requirement_id"] = req_id
        assigned[req_id] = index

    remaining = [req_id for req_id, _k, _t in verifiable if req_id not in assigned]
    return steps, remaining
