"""The fakes are test infrastructure; these tests keep them honest and conforming to ports."""

import unicodedata

import pytest

from enterprise_knowledge.domain.chat import ChatMessage, ChatRequest
from enterprise_knowledge.domain.errors import BlobNotFoundError
from enterprise_knowledge.domain.ids import JobId
from enterprise_knowledge.domain.ports import BlobStore, ChatModel, Embedder, JobQueue
from tests.fakes.blob_store import InMemoryBlobStore
from tests.fakes.chat_model import ScriptedChatModel
from tests.fakes.embedder import PRODUCTION_DIMENSION, HashEmbedder
from tests.fakes.queue import InMemoryJobQueue


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_hash_embedder_is_deterministic_and_production_sized() -> None:
    embedder: Embedder = HashEmbedder()

    first = await embedder.embed_query("Quy định nghỉ phép năm")
    second = await embedder.embed_query("Quy định nghỉ phép năm")

    assert first == second
    assert len(first) == PRODUCTION_DIMENSION == embedder.dimension


async def test_hash_embedder_treats_nfd_and_nfc_identically() -> None:
    embedder = HashEmbedder()
    text = "Chính sách bảo mật"

    nfc = await embedder.embed_query(unicodedata.normalize("NFC", text))
    nfd = await embedder.embed_query(unicodedata.normalize("NFD", text))

    assert nfc == nfd


async def test_hash_embedder_scores_shared_words_higher() -> None:
    embedder = HashEmbedder()
    query = await embedder.embed_query("vpn setup")
    related, unrelated = await embedder.embed_documents(["vpn setup guide", "lunch menu"])

    assert _cosine(query, related) > _cosine(query, unrelated)


async def test_hash_embedder_rejects_text_without_words() -> None:
    with pytest.raises(ValueError, match="word"):
        await HashEmbedder().embed_query(" ... ")


async def test_scripted_chat_model_replays_and_raises() -> None:
    model: ChatModel = ScriptedChatModel(['{"ok": true}', TimeoutError("slow")])
    request = ChatRequest(messages=(ChatMessage(role="user", content="hi"),))

    response = await model.complete(request)

    assert response.content == '{"ok": true}'
    with pytest.raises(TimeoutError):
        await model.complete(request)
    with pytest.raises(AssertionError, match="no scripted response"):
        await model.complete(request)


async def test_queue_redelivers_unacked_messages_with_count() -> None:
    queue = InMemoryJobQueue(visibility_seconds=0)  # every lease expires at once
    port: JobQueue = queue
    await port.enqueue(JobId("j1"))

    [first] = await port.receive(max_messages=10, wait_seconds=0)
    [again] = await port.receive(max_messages=10, wait_seconds=0)
    await port.ack(again)

    assert first.job_id == again.job_id == "j1"
    assert (first.delivery_count, again.delivery_count) == (1, 2)
    assert queue.depth == 0


async def test_blob_store_missing_key_raises_domain_error() -> None:
    store: BlobStore = InMemoryBlobStore()
    await store.put("a", b"data", content_type="text/plain")

    assert await store.get("a") == b"data"
    await store.delete("a")
    with pytest.raises(BlobNotFoundError):
        await store.get("a")
