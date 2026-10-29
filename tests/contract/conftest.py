"""Store implementations under contract test: the fake always, Postgres with -m integration."""

from collections.abc import AsyncIterator
from typing import Protocol

import psycopg
import pytest

from enterprise_knowledge.domain.ports import ChunkSearch, DocumentRepository
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import PRODUCTION_DIMENSION, HashEmbedder

MODEL = "fake-hash"


class Store(DocumentRepository, ChunkSearch, Protocol):
    """Both ports; production uses one Postgres adapter for both."""


async def reset_database(url: str) -> None:
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute("TRUNCATE documents, chunks CASCADE")


@pytest.fixture(
    params=["memory", pytest.param("postgres", marks=pytest.mark.integration)],
)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "memory":
        yield InMemoryDocumentStore()
        return
    url: str = request.getfixturevalue("postgres_url")
    await reset_database(url)
    postgres = await PostgresDocumentStore.connect(url, embedding_dimension=PRODUCTION_DIMENSION)
    try:
        yield postgres
    finally:
        await postgres.close()


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder(model=MODEL)
