"""Short-lived in-process bridge between base TTS and Personal Voice.

The current Voice Studio job pipeline creates base speech before entering the
personal-voice stage. Chatterbox Multilingual works better when it receives
the original text directly with the reference voice. This module lets the
base provider associate the generated audio bytes with their source text so
the personal-voice adapter can recover that text without changing persisted
job schemas or public API contracts.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

_MAX_ENTRIES = 128
_LOCK = threading.Lock()
_TEXT_BY_AUDIO_HASH: "OrderedDict[str, str]" = OrderedDict()


def _key(audio: bytes) -> str:
    return hashlib.sha256(audio).hexdigest()


def remember_source_text(audio: bytes, text: str) -> None:
    if not audio or not text:
        return
    key = _key(audio)
    with _LOCK:
        _TEXT_BY_AUDIO_HASH[key] = text
        _TEXT_BY_AUDIO_HASH.move_to_end(key)
        while len(_TEXT_BY_AUDIO_HASH) > _MAX_ENTRIES:
            _TEXT_BY_AUDIO_HASH.popitem(last=False)


def take_source_text(audio: bytes) -> str | None:
    if not audio:
        return None
    key = _key(audio)
    with _LOCK:
        return _TEXT_BY_AUDIO_HASH.pop(key, None)
