from pathlib import Path

import pytest

from enterprise_knowledge.domain.errors import BlobNotFoundError
from enterprise_knowledge.domain.ports import BlobStore
from enterprise_knowledge.infrastructure.blobs import LocalBlobStore


async def test_round_trip_and_delete(tmp_path: Path) -> None:
    store: BlobStore = LocalBlobStore(tmp_path)

    await store.put("tenant/doc-1/v1", b"%PDF-data", content_type="application/pdf")

    assert await store.get("tenant/doc-1/v1") == b"%PDF-data"
    await store.delete("tenant/doc-1/v1")
    await store.delete("tenant/doc-1/v1")  # idempotent
    with pytest.raises(BlobNotFoundError):
        await store.get("tenant/doc-1/v1")


@pytest.mark.parametrize("key", ["../escape", "a/../../b", "/abs/path", "a//b", "", "a/./b", "x y"])
async def test_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    store = LocalBlobStore(tmp_path / "blobs")

    with pytest.raises(ValueError, match=r"unsafe|escapes"):
        await store.put(key, b"x", content_type="text/plain")


async def test_overwrite_leaves_no_temporary_files(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)

    await store.put("t/d/v1", b"one", content_type="text/plain")
    await store.put("t/d/v1", b"two", content_type="text/plain")

    assert await store.get("t/d/v1") == b"two"
    assert [p.name for p in (tmp_path / "t" / "d").iterdir()] == ["v1"]
