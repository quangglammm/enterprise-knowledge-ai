"""ING-02: stable, citable, deterministic chunks."""

import itertools
import unicodedata

import pytest
from pydantic import ValidationError

from enterprise_knowledge.domain.documents import ContentType, Language
from enterprise_knowledge.domain.ids import DocumentId, chunk_id_for
from enterprise_knowledge.ingestion.chunking import (
    ChunkDraft,
    ChunkingSettings,
    build_chunks,
    chunk_document,
)
from enterprise_knowledge.ingestion.parsing import Block, BlockKind, ParsedDocument, parse_document
from tests.factories import make_document, make_policy
from tests.unit.ingestion.conftest import fixture_bytes

SMALL = ChunkingSettings(max_chars=200, overlap_chars=60)


def parsed_fixture(name: str, content_type: ContentType) -> ParsedDocument:
    return parse_document(fixture_bytes(name), content_type)


def doc(*blocks: tuple[BlockKind, str, str | None]) -> ParsedDocument:
    return ParsedDocument(
        title="t",
        blocks=tuple(Block(kind=k, text=t, section=s, page=1) for k, t, s in blocks),
    )


def sentences(n: int, word: str = "policy") -> str:
    return " ".join(f"Sentence {i} about the {word} rules applies here." for i in range(n))


ALL_FIXTURES = [
    ("leave-policy-vi.pdf", ContentType.PDF),
    ("vpn-runbook-en.docx", ContentType.DOCX),
    ("handbook-mixed.html", ContentType.HTML),
    ("onboarding-vi.md", ContentType.MARKDOWN),
]


# --- invariants on real fixtures -----------------------------------------------------


@pytest.mark.parametrize(("name", "content_type"), ALL_FIXTURES)
@pytest.mark.parametrize("settings", [ChunkingSettings(), SMALL], ids=["default", "small"])
def test_chunk_text_is_an_exact_slice_of_normalized_text(
    name: str, content_type: ContentType, settings: ChunkingSettings
) -> None:
    text, drafts = chunk_document(parsed_fixture(name, content_type), settings)

    assert drafts
    for draft in drafts:
        assert text[draft.char_start : draft.char_end] == draft.text
        assert len(draft.text) <= settings.max_chars
        assert unicodedata.is_normalized("NFC", draft.text)
    assert [d.index for d in drafts] == list(range(len(drafts)))


@pytest.mark.parametrize(("name", "content_type"), ALL_FIXTURES)
def test_chunking_is_deterministic(name: str, content_type: ContentType) -> None:
    first = chunk_document(parsed_fixture(name, content_type), SMALL)
    second = chunk_document(parsed_fixture(name, content_type), SMALL)

    assert first == second


@pytest.mark.parametrize(("name", "content_type"), ALL_FIXTURES)
def test_every_block_is_covered_by_some_chunk(name: str, content_type: ContentType) -> None:
    parsed = parsed_fixture(name, content_type)
    _, drafts = chunk_document(parsed, SMALL)

    for block in parsed.blocks:
        assert any(block.text in d.text for d in drafts) or block.text in " ".join(
            d.text for d in drafts
        )


# --- structure -----------------------------------------------------------------------


def test_headings_start_new_chunks_and_set_section() -> None:
    parsed = parsed_fixture("leave-policy-vi.pdf", ContentType.PDF)

    _, drafts = chunk_document(parsed, ChunkingSettings())

    headings = [b.text for b in parsed.blocks if b.kind is BlockKind.HEADING]
    assert [d.text.split("\n")[0] for d in drafts] == headings
    assert [d.section for d in drafts] == headings


def test_chunks_never_contain_a_later_heading() -> None:
    parsed = parsed_fixture("vpn-runbook-en.docx", ContentType.DOCX)
    headings = [b.text for b in parsed.blocks if b.kind is BlockKind.HEADING]

    _, drafts = chunk_document(parsed, SMALL)

    for draft in drafts:
        body = draft.text.removeprefix(draft.section or "")
        assert not any(f"\n\n{h}" in body for h in headings)


def test_page_is_the_page_where_the_chunk_starts() -> None:
    _, drafts = chunk_document(parsed_fixture("leave-policy-vi.pdf", ContentType.PDF), SMALL)

    pages = {d.section: d.page for d in drafts}

    assert pages["Điều 1. Phạm vi áp dụng"] == 1
    assert pages["Điều 3. Thủ tục xin nghỉ phép"] == 2


def test_language_is_detected_per_chunk() -> None:
    _, vi = chunk_document(parsed_fixture("leave-policy-vi.pdf", ContentType.PDF), SMALL)
    _, en = chunk_document(parsed_fixture("vpn-runbook-en.docx", ContentType.DOCX), SMALL)
    _, mixed = chunk_document(parsed_fixture("handbook-mixed.html", ContentType.HTML), SMALL)

    assert {d.language for d in vi} == {Language.VI}
    assert {d.language for d in en} == {Language.EN}
    assert {d.language for d in mixed} == {Language.VI, Language.EN}


# --- sizing and overlap --------------------------------------------------------------


def test_long_section_is_split_with_bounded_overlap() -> None:
    parsed = doc(
        (BlockKind.HEADING, "Rules", "Rules"), (BlockKind.PARAGRAPH, sentences(12), "Rules")
    )

    text, drafts = chunk_document(parsed, SMALL)

    assert len(drafts) > 2
    for prev, nxt in itertools.pairwise(drafts):
        overlap = prev.char_end - nxt.char_start
        assert 0 < overlap <= SMALL.overlap_chars
        assert nxt.char_start > prev.char_start  # always makes progress
    assert drafts[-1].char_end == len(text)


def test_overlap_never_crosses_sections() -> None:
    parsed = doc(
        (BlockKind.HEADING, "A", "A"),
        (BlockKind.PARAGRAPH, sentences(3), "A"),
        (BlockKind.HEADING, "B", "B"),
        (BlockKind.PARAGRAPH, sentences(3, "leave"), "B"),
    )

    _, drafts = chunk_document(parsed, SMALL)

    first_b = next(d for d in drafts if d.section == "B")
    assert first_b.text.startswith("B")
    last_a = [d for d in drafts if d.section == "A"][-1]
    assert first_b.char_start > last_a.char_end


def test_sentence_longer_than_max_is_split_on_word_boundaries() -> None:
    long_sentence = " ".join(["quyđịnh"] * 120)  # about 960 characters, no punctuation
    parsed = doc((BlockKind.PARAGRAPH, long_sentence, None))

    _, drafts = chunk_document(parsed, SMALL)

    assert len(drafts) >= 5
    assert all(len(d.text) <= SMALL.max_chars for d in drafts)
    assert all(not d.text.startswith(" ") and not d.text.endswith(" ") for d in drafts)


def test_unbreakable_token_is_hard_split() -> None:
    parsed = doc((BlockKind.PARAGRAPH, "x" * 450, None))

    _, drafts = chunk_document(parsed, SMALL)

    assert [len(d.text) for d in drafts][:2] == [200, 200]


def test_overlap_must_be_less_than_half_of_max() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        ChunkingSettings(max_chars=200, overlap_chars=100)


# --- conversion to domain chunks -----------------------------------------------------


def test_build_chunks_derives_ids_and_carries_metadata() -> None:
    document = make_document(id=DocumentId("leave"), version=2, access=make_policy())
    _, drafts = chunk_document(parsed_fixture("leave-policy-vi.pdf", ContentType.PDF), SMALL)

    chunks = build_chunks(document, drafts)

    assert [c.id for c in chunks] == [
        chunk_id_for(DocumentId("leave"), 2, i) for i in range(len(drafts))
    ]
    first, draft = chunks[0], drafts[0]
    assert first.access == document.access
    assert (first.source.page, first.source.section) == (draft.page, draft.section)
    assert (first.source.char_start, first.source.char_end) == (draft.char_start, draft.char_end)
    assert first.language is draft.language


def test_build_chunks_rejects_non_contiguous_indexes() -> None:
    draft = ChunkDraft(
        index=3, text="x", char_start=0, char_end=1, page=None, section=None, language=Language.EN
    )

    with pytest.raises(ValueError, match="index"):
        build_chunks(make_document(), [draft])
