"""Text normalization shared by ingestion and queries (ADR-0005).

Vietnamese text can encode the same diacritics as precomposed (NFC) or combining (NFD)
characters. Identical-looking words then embed and match differently, so every text
boundary normalizes to NFC.
"""

import unicodedata


def normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)
