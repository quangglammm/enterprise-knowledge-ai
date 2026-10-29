import unicodedata
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from enterprise_knowledge.domain.documents import (
    ContentType,
    Document,
    DocumentChunk,
    DocumentStatus,
    Embedding,
    Language,
    SourceLocation,
    serving_version,
    validate_chunk_set,
)
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, chunk_id_for
from tests.factories import NOW, make_document, make_policy

CHECKSUM = "a" * 64


def test_document_exposes_tenant_from_its_policy() -> None:
    document = make_document()

    assert document.tenant_id == document.access.tenant_id


@pytest.mark.parametrize("checksum", ["", "abc", "G" * 64, "A" * 64])
def test_checksum_must_be_lowercase_sha256_hex(checksum: str) -> None:
    with pytest.raises(ValidationError, match="checksum"):
        make_document(checksum=checksum)


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="created_at"):
        make_document(created_at=datetime(2026, 1, 1))


def test_failed_document_requires_error_category() -> None:
    with pytest.raises(ValidationError, match="error_category"):
        make_document(status=DocumentStatus.FAILED)


def test_with_status_returns_updated_copy() -> None:
    document = make_document()
    later = datetime(2026, 2, 1, tzinfo=UTC)

    failed = document.with_status(DocumentStatus.FAILED, now=later, error_category="corrupt")

    assert failed.status is DocumentStatus.FAILED
    assert failed.error_category == "corrupt"
    assert failed.updated_at == later
    assert document.status is DocumentStatus.PENDING


def test_documents_are_immutable() -> None:
    document = make_document()

    with pytest.raises(ValidationError):
        document.title = "changed"  # type: ignore[misc]


def test_chunk_id_is_deterministic_and_version_sensitive() -> None:
    doc = DocumentId("doc-1")

    assert chunk_id_for(doc, 1, 0) == chunk_id_for(doc, 1, 0)
    assert chunk_id_for(doc, 1, 0) != chunk_id_for(doc, 2, 0)
    assert chunk_id_for(doc, 1, 0) != chunk_id_for(doc, 1, 1)


def test_chunk_for_document_copies_policy_and_derives_id() -> None:
    document = make_document(version=3)

    chunk = DocumentChunk.for_document(
        document, index=2, text="Nghỉ phép năm", source=SourceLocation(page=1)
    )

    assert chunk.id == chunk_id_for(document.id, 3, 2)
    assert chunk.access == document.access
    assert chunk.document_version == 3


def test_chunk_with_mismatched_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="chunk id"):
        DocumentChunk(
            id=ChunkId("made-up"),
            document_id=DocumentId("doc-1"),
            document_version=1,
            chunk_index=0,
            text="text",
            source=SourceLocation(),
            access=make_policy(),
            language=Language.EN,
        )


def test_chunk_text_is_normalized_to_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "Quy định nghỉ phép")
    document = make_document()

    chunk = DocumentChunk.for_document(document, index=0, text=decomposed, source=SourceLocation())

    assert chunk.text == unicodedata.normalize("NFC", decomposed)
    assert chunk.text != decomposed


def test_blank_chunk_text_is_rejected() -> None:
    with pytest.raises(ValidationError, match="text"):
        DocumentChunk.for_document(make_document(), index=0, text="  \n ", source=SourceLocation())


def test_source_location_rejects_inverted_span() -> None:
    with pytest.raises(ValidationError, match="char_end"):
        SourceLocation(char_start=10, char_end=5)


def test_embedding_length_must_match_dimension() -> None:
    with pytest.raises(ValidationError, match="dimension"):
        Embedding(chunk_id=ChunkId("c"), model="m", dimension=3, vector=(0.1, 0.2))


def test_embedding_rejects_non_finite_values() -> None:
    with pytest.raises(ValidationError, match="finite"):
        Embedding(chunk_id=ChunkId("c"), model="m", dimension=2, vector=(0.1, float("nan")))


def test_content_type_from_mime() -> None:
    assert ContentType("application/pdf") is ContentType.PDF


def test_document_requires_version_one_or_more() -> None:
    with pytest.raises(ValidationError, match="version"):
        Document(
            id=DocumentId("d"),
            title="t",
            filename="f.pdf",
            content_type=ContentType.PDF,
            checksum=CHECKSUM,
            version=0,
            status=DocumentStatus.PENDING,
            access=make_policy(),
            language=Language.VI,
            created_at=NOW,
            updated_at=NOW,
        )


def test_serving_version_is_highest_indexed() -> None:
    versions = [
        make_document(version=1, status=DocumentStatus.INDEXED),
        make_document(version=2, status=DocumentStatus.INDEXED),
        make_document(version=3, status=DocumentStatus.PENDING),
    ]

    assert serving_version(versions) == 2
    assert serving_version([make_document(status=DocumentStatus.DELETED)]) is None


def _chunk_and_embedding(
    document: Document, index: int, model: str = "m"
) -> tuple[DocumentChunk, Embedding]:
    chunk = DocumentChunk.for_document(document, index=index, text="x", source=SourceLocation())
    return chunk, Embedding(chunk_id=chunk.id, model=model, dimension=1, vector=(1.0,))


def test_validate_chunk_set_accepts_well_formed_set() -> None:
    document = make_document()
    pairs = [_chunk_and_embedding(document, i) for i in range(3)]

    validate_chunk_set(document, [c for c, _ in pairs], [e for _, e in pairs])


def test_validate_chunk_set_rejects_mixed_embedding_models() -> None:
    document = make_document()
    c0, e0 = _chunk_and_embedding(document, 0, "model-a")
    c1, e1 = _chunk_and_embedding(document, 1, "model-b")

    with pytest.raises(ValueError, match="one model"):
        validate_chunk_set(document, [c0, c1], [e0, e1])


def test_validate_chunk_set_rejects_duplicates_and_missing_embeddings() -> None:
    document = make_document()
    chunk, embedding = _chunk_and_embedding(document, 0)

    with pytest.raises(ValueError, match="duplicate"):
        validate_chunk_set(document, [chunk, chunk], [embedding, embedding])
    with pytest.raises(ValueError, match="embedding"):
        validate_chunk_set(document, [chunk], [])
