"""Deterministic intent resolution for LUMINA Mind orchestration.

Turns free-form user chat (Greek primary, English secondary) into a structured
capability plan ``{capability, action, params, risk}``. The keyword frames are
deliberately aligned with the frontend ``studioHandoff`` heuristics so an
already-verified navigation intent maps to the same capability. Only real,
registry-backed operations are produced; anything unrecognized returns ``None``
so the advisor falls back to a conversational answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .registry import CAPABILITY_REGISTRY

CREATION_WORDS = (
    "φτιάξε", "φτιαξε", "φτιάξεις", "φτιαξεις", "δημιούργησε", "δημιουργησε",
    "δημιουργήσεις", "δημιουργησεις", "κάνε", "κανε", "κάνεις", "κανεις",
    "ετοίμασε", "ετοιμασε", "ετοιμάσεις", "ετοιμασεις", "παράγαγε", "παραγαγε",
    "generate", "create", "make", "γράψε", "γραψε", "ετοιμασέ", "ετοιμασε",
)

LIST_WORDS = ("λίστα", "λιστα", "δείξε", "δειξε", "δείξ'", "ποια", "τι", "όλα", "ολα", "list", "show", "διάλεξε", "διαλεξε")

SEARCH_WORDS = ("ψάξε", "ψαξε", "βρες", "αναζήτησε", "αναζητησε", "search", "find", "βρές")

ANALYSIS_WORDS = ("ανάλυσε", "αναλυσε", "περίληψη", "περιληψη", "summary", "analyze", "analysis", "ρίσκα", "ρισκα", "clauses", "ρήτρες", "ρητρες")

CONFIRM_WORDS = (
    "ναι", "επιβεβαίωσ", "επιβεβαίωσε", "επιβεβαιωσε", "κάνε το", "κανε το",
    "καντο", "προχώρα", "προχωρα", "προχώρησε", "προχωρησε", "εκτέλεσε",
    "εκτελεσε", "συνέχισε", "συνεχισε", "οκ", "ok", "okay", "yes", "confirm",
    "do it", "proceed", "approve", "go ahead", "βεβαιωμένα", "βεβαιωσε",
)

DECLINED_WORDS = (
    "όχι", "οχι", "μη", "μην", "ακύρωσ", "ακυρωσ", "ακύρωσε", "ακυρωσε",
    "σταμάτα", "σταματα", "no", "cancel", "stop", "decline", "don't", "dont",
    "αντίο", "αλλά", "όμως", "ομως",
)


@dataclass
class ResolvedIntent:
    capability: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def risk(self) -> str:
        operation = CAPABILITY_REGISTRY[self.capability].operations[self.action]
        return operation.risk

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "action": self.action,
            "params": self.params,
            "risk": self.risk,
        }


def _norm(value: str) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("’", "'")
    for accented, base in (
        ("ά", "α"), ("ἀ", "α"), ("ἁ", "α"), ("ἂ", "α"), ("ἃ", "α"), ("ἄ", "α"), ("ἅ", "α"), ("ὰ", "α"), ("ᾶ", "α"),
        ("έ", "ε"), ("ἐ", "ε"), ("ἑ", "ε"), ("ἒ", "ε"), ("ἓ", "ε"), ("ἔ", "ε"), ("ἕ", "ε"), ("ὲ", "ε"), ("ῆ", "η"),
        ("ή", "η"), ("ἠ", "η"), ("ἡ", "η"), ("ἢ", "η"), ("ἣ", "η"), ("ἤ", "η"), ("ἥ", "η"), ("ἦ", "η"), ("ἧ", "η"),
        ("ί", "ι"), ("ὶ", "ι"), ("ῖ", "ι"), ("ϊ", "ι"), ("ΐ", "ι"),
        ("ό", "ο"), ("ὀ", "ο"), ("ὁ", "ο"), ("ὂ", "ο"), ("ὃ", "ο"), ("ὄ", "ο"), ("ὅ", "ο"), ("ὸ", "ο"), ("ῶ", "ω"),
        ("ύ", "υ"), ("ὺ", "υ"), ("ῦ", "υ"), ("ϋ", "υ"), ("ΰ", "υ"),
        ("ώ", "ω"), ("ὠ", "ω"), ("ὡ", "ω"), ("ὢ", "ω"), ("ὣ", "ω"), ("ὤ", "ω"), ("ὥ", "ω"), ("ὦ", "ω"), ("ὧ", "ω"), ("ὼ", "ω"), ("ῳ", "ω"), ("ῴ", "ω"), ("ῳ", "ω"),
    ):
        text = text.replace(accented, base)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    return re.sub(r"[.,!?;:()\[\]{}<>|&*#+=]+", " ", text)


_STOPWORD_RE = re.compile(
    r"\s+(στ|σε|στο|στον|στην|στα|για|με|και|χωρίς|χωρις|το|τη|τον|την|τα|τις|τους|ένα|μια|μία|ενός|a|an|the|of|for|to|and)\s+"
)


def _extract_original_case(original: str, remove: list[str]) -> str:
    """Extract payload text from the original (case-preserving) message."""
    normalized_stop = {_norm(term) for term in remove}
    kept = [token for token in re.findall(r"\S+", original.strip()) if _norm(token) not in normalized_stop]
    text = _STOPWORD_RE.sub(" ", " ".join(kept))
    return text.strip(" -–—")


def _clean_params_text(message: str, remove: list[str]) -> str:
    """Strip command/keyword terms to recover the payload (title, prompt...)."""
    tokens = _norm(message).split()
    lowered = [term.lower() for term in remove]
    kept = [token for token in tokens if token not in lowered]
    text = " ".join(kept)
    text = _STOPWORD_RE.sub(" ", text)
    return text.strip(" -–—")


def _aspect_ratio(text: str) -> str | None:
    match = re.search(r"\b(9:16|16:9|1:1|4:5|3:2)\b", text)
    return match.group(1) if match else None


def _duration(text: str) -> int | None:
    match = re.search(r"\b(3|5|8)\s*(?:δευτερολεπτ[α-ω]*|sec(?:onds?)?)\b", _norm(text))
    return int(match.group(1)) if match else None


def _copy_payload(text: str) -> str:
    """Extract a payload from a creation sentence (everything after the verbs)."""
    cleaned = _clean_params_text(text, [*CREATION_WORDS, "να"])
    if not cleaned:
        return text.strip()
    return cleaned[:4000]


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _resolve_projects(text: str, context: dict[str, Any] | None, original: str = "") -> ResolvedIntent | None:
    if not _has_any(text, ("έργο", "εργο", "εργου", "εργό", "έργα", "εργα", "έργων", "εργων", "project", "projects", "εγγραφή έργου")):
        return None
    if _has_any(text, ("λίστα", "δείξε", "λιστα", "δειξε", "ποια", "όλα", "list", "show")) and _has_any(text, ("έργα", "εργα", "projects", "project")):
        return ResolvedIntent("studio", "list_projects")
    if _has_any(text, CREATION_WORDS):
        payload = _extract_original_case(
            original or text,
            [*CREATION_WORDS, "ένα", "έναν", "ενα", "νέο", "νεο", "νέα", "νεα", "καινούριο", "καινουριο", "στο", "στα", "project", "έργο", "εργο", "με", "το", "την", "όνομα", "ονομα", "ονόματι", "ονοματι", "ονομάζεται", "ονομαζεται", "λέγεται", "λεγεται", "name"],
        )
        name = payload.strip(" -–—") or "Mind Project"
        return ResolvedIntent("studio", "create_project", {"name": name[:200], "description": (original or text).strip()[:2000]})
    return None


def _resolve_code_builder(text: str) -> ResolvedIntent | None:
    if not _has_any(text, ("κώδικα", "κωδικα", "code", "κώδικες", "κωδικες", "refactor", "bug στο", "σφάλμα στο", "σφαλμα στο")):
        return None
    if _has_any(text, ("status", "κατάσταση", "κατασταση", "υγεία", "υγεια", "έτοιμος", "ετοιμος")):
        return ResolvedIntent("code_builder", "health")
    if not _has_any(text, CONFIRM_WORDS):
        prompt = _copy_payload(text)
        return ResolvedIntent("code_builder", "plan", {"prompt": prompt})
    return None


def _resolve_documents(text: str, context: dict[str, Any] | None, original: str = "") -> ResolvedIntent | None:
    target_hits = (
        "έγγραφο", "εγγραφο", "έγγραφα", "εγγραφα", "συμφωνητικό", "συμφωνητικο",
        "συμφωνητικά", "συμφωνητικα", "σύμβαση", "συμβαση", "συμβόλαιο", "συμβολαιο",
        "επιστολή", "επιστολη", "document", "documents", "pdf", "word", "ρχείο",
        "αρχείο", "αρχειο", "τιμολόγιο", "τιμολογιο", "invoice", "βιογραφικό", "βιογραφικο",
        "cv", "πλάνο", "πλανο", "παρουσίαση", "παρουσιαση", "αίτηση", "αιτηση",
    )
    if not _has_any(text, target_hits):
        return None

    document_id = _document_id_from_context(context)
    if document_id and _has_any(text, ("νομικ", "legal", "κίνδυν", "κινδυν", "ρίσκα", "ρισκα", "συμμόρφωσ", "συμμορφωσ")):
        return ResolvedIntent("documents", "legal_review", {"document_id": document_id})

    if _has_any(text, ("ανάλυσ", "αναλυσ", "περίληψη", "περιληψη", "summary", "analy")) and _has_any(text, target_hits):
        if document_id:
            params: dict[str, Any] = {"document_id": document_id}
            if _has_any(text, ("περίληψη", "περιληψη", "summary", "summarize")):
                params["action"] = "summarize"
            if _has_any(text, ("ρίσκα", "ρισκα", "risks")):
                params["question"] = "What are the material risks and required obligations?"
            return ResolvedIntent("documents", "analysis", params)
        return None

    if _has_any(text, ("λίστα", "λιστα", "δείξε", "δειξε", "ποια", "τι έγγραφα", "όλα τα", "list", "show", "δείξ")):
        if _has_any(text, SEARCH_WORDS):
            q = _clean_params_text(text, [*SEARCH_WORDS, "για", "από", "έγγραφα", "εγγραφα", "έγγραφο", "εγγραφο", "στα", "στο"])
            if len(q) < 2:
                return None
            return ResolvedIntent("documents", "search", {"text": q[:200]})
        return ResolvedIntent("documents", "list")

    if _has_any(text, SEARCH_WORDS):
        q = _clean_params_text(text, [*SEARCH_WORDS, "έγγραφα", "εγγραφα", "έγγραφο", "εγγραφο", "συμφωνητικό", "συμφωνητικο", "για", "στα", "στο"])
        return ResolvedIntent("documents", "search", {"text": q[:200]}) if q else None

    if _has_any(text, CREATION_WORDS):
        if _has_any(text, ("συμφωνητικό", "συμφωνητικο", "σύμβαση", "συμβαση", "συμβόλαιο", "συμβολαιο", "παρουσίασ", "παρουσιασ", "επιστολ", "τιμολόγιο", "τιμολογιο", "βιογραφ", "αίτησ", "αιτησ")):
            title = _auto_title(original or text, "Συμφωνητικό")
            return ResolvedIntent(
                "documents",
                "generate",
                {
                    "title": title,
                    "prompt": _copy_payload(text) or title,
                    "creation_mode": "prompt",
                    "language": "el",
                    "country": "GR",
                },
            )
        title = _auto_title(original or text, "Έγγραφο")
        return ResolvedIntent(
            "documents",
            "create",
            {
                "title": title,
                "content_text": "",
                "document_type": "document",
                "language": _language(text),
            },
        )
    return None


def _auto_title(original: str, fallback: str) -> str:
    cleaned = _extract_original_case(
        original,
        [*CREATION_WORDS, "ένα", "μια", "ενα", "εναν", "το", "τη", "συμφωνητικό", "συμφωνητικο",
         "σύμβαση", "συμβαση", "συμβόλαιο", "συμβολαιο", "έγγραφο", "εγγραφο", "επιστολή", "επιστολη",
         "document", "για", "μου", "χρήστη", "χρηστη", "που", "με"],
    )
    title = re.sub(r"\s+", " ", cleaned).strip(" -–—")
    return title[:180] or fallback


def _language(text: str) -> str:
    return "el" if re.search(r"[α-ωάέήίόύώίύ]|ά|έ|ή|ί|ό|ύ|ώ", text) else "en"


def _document_id_from_context(context: dict[str, Any] | None) -> str | None:
    documents = (context or {}).get("documents") or []
    if not documents:
        return None
    documents = [doc for doc in documents if isinstance(doc, dict) and doc.get("id")]
    if len(documents) != 1:
        return None
    return str(documents[0]["id"])


def _resolve_image(text: str, original: str = "") -> ResolvedIntent | None:
    if not _has_any(text, ("φωτογραφία", "φωτογραφια", "φωτό", "φωτο", "εικόνα", "εικονα", "εικόνες", "εικονες", "image", "photo", "poster", "αφίσα", "αφισα", "εικονάκι", "εικονάκι")):
        return None
    if _has_any(text, ("λίστα", "λιστα", "δείξε", "δειξε", "γαλαρί", "γαλαρι", "gallery", "έχω", "τι έχω")):
        return ResolvedIntent("image", "list_gallery")
    if _has_any(text, CREATION_WORDS):
        prompt = _copy_payload(text)
        if len(prompt) < 3:
            return None
        params: dict[str, Any] = {"prompt": prompt}
        aspect = _aspect_ratio(original or text)
        if aspect:
            params["aspect_ratio"] = aspect
        return ResolvedIntent("image", "generate", params)
    return None


def _resolve_video(text: str, original: str = "") -> ResolvedIntent | None:
    if not _has_any(text, ("βίντεο", "βιντεο", "video", "reel", "animation", "ταινία", "ταινια", "κινούμεν")):
        return None
    if _has_any(text, ("λίστα", "λιστα", "δείξε", "δειξε", "ποια", "jobs")):
        return ResolvedIntent("video", "list_jobs")
    if _has_any(text, CREATION_WORDS):
        prompt = _copy_payload(text)
        if len(prompt) < 3:
            return None
        params: dict[str, Any] = {"prompt": prompt, "mode": "text-to-video"}
        if _aspect_ratio(original or text):
            params["aspect_ratio"] = _aspect_ratio(original or text)
        if _duration(original or text):
            params["duration_seconds"] = _duration(original or text)
        return ResolvedIntent("video", "generate", params)
    return None


def _resolve_voice(text: str) -> ResolvedIntent | None:
    if not _has_any(text, ("φωνή", "φωνη", "ηχητικό", "ηχητικο", "αφήγηση", "αφηγηση", "voice", "audio", "εκφώνησ", "εκφωνησ", "διάβασε", "διαβασε", "διάβασέ", "διαβασε", "πες μου", "βόις")):
        return None
    if _has_any(text, ("λίστα", "λιστα", "δείξε", "δειξε", "ποια", "jobs")):
        return ResolvedIntent("voice", "list_jobs")
    if _has_any(text, CREATION_WORDS + ("διάβασε", "διαβασε", "διάβασέ", "εκφώνησε", "εκφωνησε")):
        payload = _copy_payload(text)
        if len(payload) < 3:
            return None
        params: dict[str, Any] = {"text": payload, "mode": "text-to-speech", "style": "podcast", "output_format": "wav"}
        if _has_any(text, ("ανδρ", "άνδρ", "αντρας", "ανοιχτη")):
            params["voice"] = "andreas"
        elif _has_any(text, ("γυναικ", "γυναικ")):
            params["voice"] = "ariadni"
        return ResolvedIntent("voice", "generate", params)
    return None


_CAPABILITY_TRIGGERS = (
    "έγγραφο", "εγγραφο", "έγγραφα", "εγγραφα", "συμφωνητικό", "συμφωνητικο",
    "σύμβαση", "συμβαση", "συμβόλαιο", "συμβολαιο", "επιστολή", "επιστολη",
    "τιμολόγιο", "τιμολογιο", "παρουσίασ", "παρουσιασ", "βιογραφ", "αίτησ", "αιτησ",
    "document", "documents", "pdf", "word", "cv",
    "φωτογραφία", "φωτογραφια", "φωτό", "φωτο", "εικόνα", "εικονα", "εικόνες", "εικονες",
    "image", "photo", "poster", "αφίσα", "αφισα",
    "βίντεο", "βιντεο", "video", "reel", "animation", "ταινία", "ταινια",
    "φωνή", "φωνη", "ηχητικό", "ηχητικο", "αφήγηση", "αφηγηση", "voice", "audio",
    "εκφώνησ", "εκφωνησ", "διάβασε", "διαβασε",
    "έργο", "εργο", "έργα", "εργα", "project", "projects",
    "κώδικα", "κωδικα", "κώδικες", "κωδικες", "code", "refactor",
)


def _mentions_capability(text: str) -> bool:
    return _has_any(text, _CAPABILITY_TRIGGERS)


def resolve_intent(message: str, context: dict[str, Any] | None = None) -> ResolvedIntent | None:
    """Resolve a user message to a registry-backed capability plan (or None)."""
    text = _norm(message)
    if not text:
        return None
    if detect_confirmation(text) is not None and not _mentions_capability(text):
        return None

    for resolver in (
        _resolve_code_builder,
        _resolve_documents,
        _resolve_projects,
        _resolve_video,
        _resolve_voice,
        _resolve_image,
    ):
        if resolver in (_resolve_documents, _resolve_projects):
            intent = resolver(text, context, message)
        elif resolver in (_resolve_image, _resolve_video):
            intent = resolver(text, message)
        else:
            intent = resolver(text)
        if intent is not None:
            try:
                operation = CAPABILITY_REGISTRY[intent.capability].operations[intent.action]
                required = set(operation.required_params) - set(intent.params)
                if not required:
                    return intent
            except KeyError:
                return None
    return None


def detect_confirmation(message: str) -> str | None:
    """Return 'approve' / 'decline' for a pending-action confirmation, else None."""
    text = _norm(message)
    if not text:
        return None
    if _has_any(text, ("αλλά", "όμως", "αλλα", "ομως", "however", "but ", "χρειάζομα", "χρειαζομα", "μπορεί", "μπορει", "επιπλέον", "επιπλεον", "και μετά", "και μετα")):
        return None
    if _has_any(text, DECLINED_WORDS) and len(text.split()) <= 4:
        return "decline"
    if _has_any(text, CONFIRM_WORDS) and len(text.split()) <= 6:
        return "approve"
    return None