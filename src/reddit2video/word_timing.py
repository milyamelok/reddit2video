from __future__ import annotations

import re
from typing import Any


WORD_CORE_RE = r"\d+(?:[.,]\d+)*(?:[-–—]\d+(?:[.,]\d+)*)?(?:[%％])?|[^\W\d_]+(?:[-'’][^\W\d_]+)*"
LEADING_WORD_PUNCT_RE = r"[\"'«„“‘]*"
TRAILING_WORD_PUNCT_RE = r"[\"'»“”‘’.,!?;:…]*"

WORD_TOKEN_RE = re.compile(
    rf"{LEADING_WORD_PUNCT_RE}(?:{WORD_CORE_RE}){TRAILING_WORD_PUNCT_RE}",
    re.UNICODE,
)

MEASUREMENT_UNITS = {
    "%",
    "кг",
    "килограмм",
    "килограмма",
    "килограммов",
    "г",
    "гр",
    "грамм",
    "грамма",
    "граммов",
    "см",
    "сантиметр",
    "сантиметра",
    "сантиметров",
    "м",
    "метр",
    "метра",
    "метров",
    "л",
    "литр",
    "литра",
    "литров",
    "мл",
    "миллилитр",
    "миллилитра",
    "миллилитров",
    "сек",
    "секунда",
    "секунды",
    "секунд",
    "мин",
    "минута",
    "минуты",
    "минут",
    "час",
    "часа",
    "часов",
}


def align_words_to_character_alignment(
    voiceover_text: str,
    alignment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Group exact source characters into word-ish tokens and time each token by its first character."""
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    alignment_text = "".join(str(character) for character in characters)
    duration = _last_number(ends) or _last_number(starts) or 0.0
    source_text = voiceover_text or alignment_text
    direct_indexing = bool(source_text and alignment_text and source_text == alignment_text)
    cursor = 0
    warnings: list[str] = []
    words: list[dict[str, Any]] = []

    for word_index, match in enumerate(WORD_TOKEN_RE.finditer(source_text), start=1):
        token = match.group(0)
        source_start = match.start()
        source_end = match.end()
        confidence = 1.0
        alignment_start = source_start
        alignment_length = len(token)

        if not direct_indexing:
            found, matched_length = _find_token_match(alignment_text, token, cursor)
            if found >= 0:
                alignment_start = found
                alignment_length = matched_length
                cursor = found + matched_length
                confidence = 0.85
            else:
                warnings.append(f"Could not find exact word token #{word_index} in alignment text: {token!r}.")
                alignment_start = source_start
                confidence = 0.45

        alignment_end = alignment_start + alignment_length - 1
        start_sec = _time_at(starts, alignment_start, forward=True)
        end_sec = _time_at(ends, alignment_end, forward=False)
        if start_sec is None:
            text_len = max(1, len(source_text))
            start_sec = duration * (source_start / text_len)
            confidence = min(confidence, 0.5)
            warnings.append(f"Missing start timestamp for word token #{word_index}; used proportional fallback.")
        if end_sec is None:
            text_len = max(1, len(source_text))
            end_sec = duration * (source_end / text_len)
            confidence = min(confidence, 0.5)
            warnings.append(f"Missing end timestamp for word token #{word_index}; used proportional fallback.")
        if end_sec < start_sec:
            end_sec = start_sec

        words.append(
            {
                "word_index": word_index,
                "word": token,
                "source_start_char": source_start,
                "source_end_char": source_end,
                "alignment_start_char": max(0, alignment_start),
                "alignment_end_char": max(0, alignment_end),
                "start_sec": round(float(start_sec), 3),
                "end_sec": round(float(end_sec), 3),
                "appear_sec": round(float(start_sec), 3),
                "timing_strategy": "first_character",
                "confidence": round(confidence, 3),
            }
        )

    return words, warnings


def normalize_timed_word_tokens(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply render-facing token grouping rules to timed words.

    The audio aligner times word-ish units, but typography wants a slightly
    different surface: punctuation stays with the preceding token, measurement
    units stay with their numbers, and low-confidence fallback tokens should not
    create lonely visual beats.
    """

    normalized: list[dict[str, Any]] = []
    for word in words:
        token = str(word.get("word") or "")
        if not token:
            continue
        if normalized and should_attach_to_previous(token, word):
            previous = normalized[-1]
            previous["word"] = attach_token_text(str(previous.get("word") or ""), token)
            previous["source_end_char"] = max(
                int(previous.get("source_end_char") or 0),
                int(word.get("source_end_char") or 0),
            )
            previous["alignment_end_char"] = max(
                int(previous.get("alignment_end_char") or 0),
                int(word.get("alignment_end_char") or 0),
            )
            previous["end_sec"] = max(float(previous.get("end_sec") or 0), float(word.get("end_sec") or 0))
            previous["confidence"] = round(
                min(float(previous.get("confidence") or 1), float(word.get("confidence") or 1)),
                3,
            )
            previous["timing_strategy"] = f"{previous.get('timing_strategy') or 'first_character'}+attached_token"
            continue
        normalized.append(dict(word))

    for index, word in enumerate(normalized, start=1):
        word["word_index"] = index
    return normalized


def should_attach_to_previous(token: str, word: dict[str, Any]) -> bool:
    stripped = token.strip()
    if not stripped:
        return True
    core = normalize_token_core(stripped)
    if not core:
        return True
    if core in MEASUREMENT_UNITS:
        return True
    if float(word.get("confidence") or 1) <= 0.5:
        return True
    return False


def attach_token_text(previous: str, token: str) -> str:
    if not previous:
        return token
    stripped = token.strip()
    core = normalize_token_core(stripped)
    if core in MEASUREMENT_UNITS:
        return f"{previous} {stripped}"
    if re.fullmatch(r"[^\wА-Яа-яЁё0-9]+", stripped, flags=re.UNICODE):
        return f"{previous}{stripped}"
    return f"{previous} {stripped}"


def normalize_token_core(token: str) -> str:
    return re.sub(r"^[^\wА-Яа-яЁё0-9%％]+|[^\wА-Яа-яЁё0-9%％]+$", "", token, flags=re.UNICODE).lower().replace("ё", "е")


def _find_token_match(alignment_text: str, token: str, cursor: int) -> tuple[int, int]:
    for variant in _token_alignment_variants(token):
        found = alignment_text.find(variant, cursor)
        if found >= 0:
            return found, len(variant)
        found = alignment_text.find(variant)
        if found >= 0:
            return found, len(variant)

    normalized_alignment = _normalize_alignment_text(alignment_text)
    for variant in _token_alignment_variants(token):
        normalized_token = _normalize_alignment_text(variant)
        found = normalized_alignment.find(normalized_token, cursor)
        if found >= 0:
            return found, len(variant)
        found = normalized_alignment.find(normalized_token)
        if found >= 0:
            return found, len(variant)
    return -1, len(token)


def _token_alignment_variants(token: str) -> list[str]:
    variants = [token]
    loanword = _loanword_alignment_variant(token)
    if loanword and loanword not in variants:
        variants.append(loanword)
    return variants


def _loanword_alignment_variant(token: str) -> str:
    leading = re.match(r"^\W*", token, flags=re.UNICODE).group(0)
    trailing = re.search(r"\W*$", token, flags=re.UNICODE).group(0)
    core = normalize_token_core(token)
    pilates_suffixes = {
        "пилатес": "",
        "пилатеса": "а",
        "пилатесу": "у",
        "пилатесом": "ом",
        "пилатесе": "е",
    }
    if core in pilates_suffixes:
        suffix = pilates_suffixes[core]
        replacement = "pilates" if not suffix else f"pilates-{suffix}"
        return f"{leading}{replacement}{trailing}"
    if core == "латте":
        return f"{leading}latte{trailing}"
    return ""


def _normalize_alignment_text(value: str) -> str:
    return value.lower().replace("ё", "е")


def _time_at(values: list[Any], index: int, *, forward: bool) -> float | None:
    if not values:
        return None
    index = max(0, min(index, len(values) - 1))
    step = 1 if forward else -1
    current = index
    while 0 <= current < len(values):
        value = values[current]
        if isinstance(value, (int, float)):
            return float(value)
        current += step
    return None


def _last_number(values: list[Any]) -> float | None:
    for value in reversed(values):
        if isinstance(value, (int, float)):
            return float(value)
    return None
