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
PACKED_SMALL = ChunkingSettings(max_chars=200, overlap_chars=60, pack_sections=True)


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
@pytest.mark.parametrize(
    "settings", [ChunkingSettings(), SMALL, PACKED_SMALL], ids=["default", "small", "packed"]
)
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
@pytest.mark.parametrize("settings", [SMALL, PACKED_SMALL], ids=["small", "packed"])
def test_every_body_block_is_covered_and_every_heading_survives(
    name: str, content_type: ContentType, settings: ChunkingSettings
) -> None:
    parsed = parsed_fixture(name, content_type)
    text, drafts = chunk_document(parsed, settings)
    covered = [False] * len(text)
    for draft in drafts:
        covered[draft.char_start : draft.char_end] = [True] * (draft.char_end - draft.char_start)

    offset = 0
    for block in parsed.blocks:
        start = text.index(block.text, offset)
        offset = start + len(block.text)
        if block.kind is BlockKind.HEADING:
            # A heading appears in a chunk's text, or at least as some chunk's section.
            assert all(covered[start:offset]) or any(d.section == block.text for d in drafts)
        else:
            assert all(covered[start:offset]), block.text


# --- structure -----------------------------------------------------------------------


def test_headings_start_new_chunks_and_set_section() -> None:
    parsed = parsed_fixture("leave-policy-vi.pdf", ContentType.PDF)

    _, drafts = chunk_document(parsed, ChunkingSettings())

    headings = [b.text for b in parsed.blocks if b.kind is BlockKind.HEADING]
    assert [d.text.split("\n")[0] for d in drafts] == headings
    assert [d.section for d in drafts] == headings


@pytest.mark.parametrize(("name", "content_type"), ALL_FIXTURES)
def test_chunks_never_span_two_sections(name: str, content_type: ContentType) -> None:
    """Headings may only lead a chunk; once body text starts, no heading may follow."""
    parsed = parsed_fixture(name, content_type)
    headings = {b.text for b in parsed.blocks if b.kind is BlockKind.HEADING}

    _, drafts = chunk_document(parsed, SMALL)

    for draft in drafts:
        seen_body = False
        for part in draft.text.split("\n\n"):
            if part in headings:
                assert not seen_body, draft.text
            else:
                seen_body = True


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


def test_consecutive_headings_merge_into_the_following_chunk() -> None:
    parsed = doc(
        (BlockKind.HEADING, "VPN access runbook", "VPN access runbook"),
        (BlockKind.HEADING, "Purpose", "Purpose"),
        (BlockKind.PARAGRAPH, "This runbook explains the VPN.", "Purpose"),
        (BlockKind.HEADING, "Steps", "Steps"),
        (BlockKind.PARAGRAPH, "Open the client.", "Steps"),
    )

    _, drafts = chunk_document(parsed, ChunkingSettings())

    assert [d.text for d in drafts] == [
        "VPN access runbook\n\nPurpose\n\nThis runbook explains the VPN.",
        "Steps\n\nOpen the client.",
    ]
    assert [d.section for d in drafts] == ["Purpose", "Steps"]


@pytest.mark.parametrize(("name", "content_type"), ALL_FIXTURES)
@pytest.mark.parametrize("settings", [SMALL, PACKED_SMALL], ids=["small", "packed"])
def test_no_chunk_is_only_headings(
    name: str, content_type: ContentType, settings: ChunkingSettings
) -> None:
    parsed = parsed_fixture(name, content_type)
    headings = {b.text for b in parsed.blocks if b.kind is BlockKind.HEADING}

    _, drafts = chunk_document(parsed, settings)

    for draft in drafts:
        assert not set(draft.text.split("\n\n")) <= headings, draft.text


# --- section packing (opt-in) --------------------------------------------------------

THREE_SHORT_SECTIONS = (
    (BlockKind.HEADING, "Leave", "Leave"),
    (BlockKind.PARAGRAPH, "Staff get 14 days.", "Leave"),
    (BlockKind.HEADING, "Carry-over", "Carry-over"),
    (BlockKind.PARAGRAPH, "Up to 3 days carry over.", "Carry-over"),
    (BlockKind.HEADING, "Requests", "Requests"),
    (BlockKind.PARAGRAPH, "Ask 3 days ahead.", "Requests"),
)


def test_section_packing_is_off_by_default() -> None:
    _, drafts = chunk_document(doc(*THREE_SHORT_SECTIONS), ChunkingSettings())

    assert not ChunkingSettings().pack_sections
    assert [d.section for d in drafts] == ["Leave", "Carry-over", "Requests"]


def test_packing_puts_short_sections_that_fit_into_one_chunk() -> None:
    _, drafts = chunk_document(doc(*THREE_SHORT_SECTIONS), PACKED_SMALL)

    assert [d.text for d in drafts] == [
        "Leave\n\nStaff get 14 days.\n\nCarry-over\n\nUp to 3 days carry over."
        "\n\nRequests\n\nAsk 3 days ahead."
    ]
    assert drafts[0].section == "Leave"  # the section where the chunk starts


def test_packing_starts_a_new_chunk_when_the_whole_next_section_does_not_fit() -> None:
    body = sentences(2)  # about 100 characters
    parsed = doc(
        (BlockKind.HEADING, "First", "First"),
        (BlockKind.PARAGRAPH, body, "First"),
        (BlockKind.HEADING, "Second", "Second"),
        (BlockKind.PARAGRAPH, body, "Second"),
    )

    _, drafts = chunk_document(parsed, PACKED_SMALL)

    assert [d.section for d in drafts] == ["First", "Second"]
    assert [d.text.split("\n\n")[0] for d in drafts] == ["First", "Second"]


def test_packing_splits_a_long_section_like_the_default() -> None:
    parsed = doc(
        (BlockKind.HEADING, "Long", "Long"),
        (BlockKind.PARAGRAPH, sentences(12), "Long"),
    )

    assert chunk_document(parsed, PACKED_SMALL)[1] == chunk_document(parsed, SMALL)[1]
