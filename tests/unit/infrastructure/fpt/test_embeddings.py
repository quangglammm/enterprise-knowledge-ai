"""FptEmbedder: texts to /embeddings and back to validated vectors of the index dimension."""

from typing import Any

import httpx
import pytest

from enterprise_knowledge.domain.errors import ModelResponseError
from enterprise_knowledge.domain.ports import Embedder
from enterprise_knowledge.infrastructure.fpt.embeddings import FptEmbedder
from tests.unit.infrastructure.fpt.conftest import Harness, ok

MODEL = "Vietnamese_Embedding"
DIM = 4


def vectors(*rows: list[float], ordered: bool = True) -> dict[str, Any]:
    data = [{"object": "embedding", "index": i, "embedding": row} for i, row in enumerate(rows)]
    return {"model": MODEL, "data": data if ordered else data[::-1]}


def embedder(harness: Harness) -> FptEmbedder:
    return FptEmbedder(harness.client, model=MODEL, dimension=DIM)


async def test_documents_are_embedded_in_one_request() -> None:
    harness = Harness(ok(vectors([1, 0, 0, 0], [0, 1, 0, 0])))
    port: Embedder = embedder(harness)

    result = await port.embed_documents(["Nghỉ phép năm", "VPN setup"])

    assert result == [(1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)]
    assert harness.transport.requests[0].url.path == "/embeddings"
    assert harness.transport.body() == {"model": MODEL, "input": ["Nghỉ phép năm", "VPN setup"]}
    assert (port.model, port.dimension) == (MODEL, DIM)


async def test_results_are_ordered_by_index() -> None:
    harness = Harness(ok(vectors([1, 0, 0, 0], [0, 1, 0, 0], ordered=False)))

    result = await embedder(harness).embed_documents(["a", "b"])

    assert result == [(1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)]


async def test_query_is_a_single_embedding() -> None:
    harness = Harness(ok(vectors([0, 0, 1, 0])))

    assert await embedder(harness).embed_query("q") == (0.0, 0.0, 1.0, 0.0)
    assert harness.transport.body()["input"] == ["q"]


async def test_no_texts_means_no_request() -> None:
    harness = Harness()

    assert await embedder(harness).embed_documents([]) == []
    assert harness.transport.requests == []


@pytest.mark.parametrize(
    "body",
    [
        vectors([1, 0, 0]),
        vectors([1, 0, 0, 0], [0, 1, 0, 0]),
        vectors([1, 0, 0, "x"]),  # type: ignore[list-item]
        {"model": MODEL},
        {"data": [{"index": 5, "embedding": [1, 0, 0, 0]}]},
    ],
    ids=["wrong-dimension", "too-many", "non-number", "no-data", "bad-index"],
)
async def test_unusable_vectors_are_a_response_error(body: dict[str, Any]) -> None:
    harness = Harness(ok(body))

    with pytest.raises(ModelResponseError):
        await embedder(harness).embed_documents(["only one"])


async def test_overflowing_values_are_a_response_error() -> None:
    overflow = '{"data": [{"index": 0, "embedding": [1, 0, 0, 1e400]}]}'  # parses as inf
    harness = Harness(httpx.Response(200, text=overflow))

    with pytest.raises(ModelResponseError, match="non-finite"):
        await embedder(harness).embed_documents(["only one"])
