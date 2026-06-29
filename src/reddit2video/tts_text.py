from __future__ import annotations

import re


_CYRILLIC_WORD_RE = re.compile(r"[А-Яа-яЁё]+")


def normalize_russian_tts_orthography(text: str) -> str:
    """Remove artificial stress capitalization from Russian TTS text.

    The video renderer reuses the TTS scene text for word-sync overlays, so
    pronunciation hints like "килограммОвого" must not leak into visible text.
    Keep normal sentence/proper-noun capitalization, but lowercase internal
    Cyrillic capitals inside mixed-case words.
    """

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        has_lower = any(ch.islower() for ch in word)
        has_upper = any(ch.isupper() for ch in word)
        if not (has_lower and has_upper):
            return word
        chars = [word[0]]
        chars.extend(ch.lower() if ch.isupper() else ch for ch in word[1:])
        return "".join(chars)

    return _CYRILLIC_WORD_RE.sub(replace, text)
