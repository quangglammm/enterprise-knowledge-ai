import unicodedata

import pytest

from enterprise_knowledge.ingestion.normalize import normalize_text


def test_composes_vietnamese_to_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "Nghỉ phép năm")

    assert normalize_text(decomposed) == "Nghỉ phép năm"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Điều  2.  Số  ngày\nnghỉ", "Điều 2. Số ngày nghỉ"),
        ("  leading and trailing \t", "leading and trailing"),
        ("zero​width﻿ joiner‍", "zerowidth joiner"),
        ("control\x00\x07 chars", "control chars"),
        ("ﬁle ﬂow", "file flow"),
    ],
)
def test_cleans_pdf_artifacts(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_is_idempotent() -> None:
    once = normalize_text(" ﬁ  Quy​ định \n nghỉ ")

    assert normalize_text(once) == once
