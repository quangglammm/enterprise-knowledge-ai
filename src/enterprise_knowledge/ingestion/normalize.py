"""Text normalization applied to every extracted block (ADR-0006). Idempotent."""

import re
import unicodedata

from enterprise_knowledge.domain.text import normalize_nfc

_LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_WHITESPACE = re.compile(r"\s+")


def _is_control(char: str) -> bool:
    return unicodedata.category(char) == "Cc" and not char.isspace()


def normalize_text(text: str) -> str:
    """NFC, ligatures expanded, invisible and control characters removed, whitespace collapsed."""
    cleaned = normalize_nfc(text).translate(_LIGATURES).translate(_ZERO_WIDTH)
    cleaned = "".join(c for c in cleaned if not _is_control(c))
    return _WHITESPACE.sub(" ", cleaned).strip()
