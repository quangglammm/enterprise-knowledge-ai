from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_knowledge.domain.ids import DocumentId
from enterprise_knowledge.ingestion.delete import DeleteDocument
from enterprise_knowledge.ingestion.ingest import IngestDocument
from tests.factories import TENANT, make_principal
from tests.fakes.blob_store import InMemoryBlobStore
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder

FIXTURES = Path(__file__).resolve().parents[3] / "datasets" / "fixtures"
T0 = datetime(2026, 3, 1, tzinfo=UTC)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class Harness:
    """Ingestion use cases wired to in-memory fakes, with a fixed clock and sequential IDs."""

    def __init__(self) -> None:
        self.store = InMemoryDocumentStore()
        self.blobs = InMemoryBlobStore()
        self.embedder = HashEmbedder()
        self.ids = iter(f"doc-{i}" for i in range(1, 100))
        self.ingest = IngestDocument(
            documents=self.store,
            embedder=self.embedder,
            blobs=self.blobs,
            clock=lambda: T0,
            new_document_id=lambda: DocumentId(next(self.ids)),
        )
        self.delete = DeleteDocument(documents=self.store, blobs=self.blobs)

    async def search(self, query: str, *groups: str) -> list[tuple[str, int]]:
        """Distinct (document, version) pairs among the hits, in rank order."""
        hits = await self.store.search(
            make_principal(TENANT, *groups),
            await self.embedder.embed_query(query),
            k=5,
            embedding_model=self.embedder.model,
        )
        return list(dict.fromkeys((h.document_id, h.document_version) for h in hits))


@pytest.fixture
def harness() -> Harness:
    return Harness()
