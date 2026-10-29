"""Dependency-free Vietnamese/English detection (ADR-0006).

Almost every Vietnamese syllable carries a tone mark or a Vietnamese-specific letter, while
English text only contains them in proper names. The share of marked words separates the
two reliably at chunk granularity.
"""

import re
import unicodedata
from collections.abc import Iterable

from enterprise_knowledge.domain.documents import Language

# breve, circumflex, horn (letters) and grave, acute, tilde, hook above, dot below (tones)
_VI_MARKS = frozenset("̛̣̆̂̀́̃̉")
_VI_WORD_SHARE = 0.25
_MIXED_SHARE = 0.2
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _is_vietnamese_letter(char: str) -> bool:
    if char in "đĐ":
        return True
    decomposed = unicodedata.normalize("NFD", char)
    return len(decomposed) > 1 and any(mark in _VI_MARKS for mark in decomposed[1:])


def detect_language(text: str) -> Language:
    words = _WORD.findall(text)
    if not words:
        return Language.UNKNOWN
    marked = sum(1 for w in words if any(_is_vietnamese_letter(c) for c in w))
    return Language.VI if marked / len(words) >= _VI_WORD_SHARE else Language.EN


def document_language(parts: Iterable[tuple[Language, int]]) -> Language:
    """Combine per-chunk languages weighted by character count."""
    totals = {Language.VI: 0, Language.EN: 0}
    for language, size in parts:
        if language in totals:
            totals[language] += size
    known = totals[Language.VI] + totals[Language.EN]
    if known == 0:
        return Language.UNKNOWN
    vi_share = totals[Language.VI] / known
    if _MIXED_SHARE <= vi_share <= 1 - _MIXED_SHARE:
        return Language.MIXED
    return Language.VI if vi_share > 0.5 else Language.EN
