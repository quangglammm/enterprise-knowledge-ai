import pytest

from enterprise_knowledge.domain.documents import Language
from enterprise_knowledge.ingestion.language import detect_language, document_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Người lao động được nghỉ 12 ngày làm việc mỗi năm.", Language.VI),
        ("Open the VPN client and select the closest gateway.", Language.EN),
        (
            "Engineers based in Hanoi and Ho Chi Minh City join the on-call rotation, "
            "which covers the Đà Nẵng office as well.",
            Language.EN,
        ),
        ("12 / 2026 - 08:30", Language.UNKNOWN),
        ("", Language.UNKNOWN),
    ],
)
def test_detect_language(text: str, expected: Language) -> None:
    assert detect_language(text) is expected


def test_document_language_is_mixed_when_both_are_substantial() -> None:
    parts = [(Language.VI, 600), (Language.EN, 400)]

    assert document_language(parts) is Language.MIXED


def test_document_language_follows_dominant_language() -> None:
    assert document_language([(Language.VI, 950), (Language.EN, 50)]) is Language.VI
    assert document_language([(Language.EN, 500), (Language.UNKNOWN, 500)]) is Language.EN
    assert document_language([]) is Language.UNKNOWN
